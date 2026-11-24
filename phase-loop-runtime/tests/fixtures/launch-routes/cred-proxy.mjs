#!/usr/bin/env node
// Credential-injecting forward proxy that runs OUTSIDE the bubblewrap sandbox
// (Consiliency/agent-toolkit#6), in the bwrap-launch.mjs process. It has no listening socket:
// inner-forward.mjs accepts each connection on 127.0.0.1:<port> inside the sandbox and passes the
// connected socket out over its IPC channel, and the launcher hands it to this server. A request for /<provider>/<path>
// goes to that provider's allowlisted HTTPS origin with the real credential; any other route is
// refused. The child holds only placeholders.
//
// Credentials come from Pi's own auth resolution (ModelRuntime.getAuth), run here with the host's
// models.json and auth.json: models.json key commands (a 1Password `op read`, say), API keys, and
// OAuth subscriptions (openai "Sign in with ChatGPT", xai). An OAuth token that expires within five
// minutes is refreshed by Pi under its auth.json lock and written back, exactly as the parent Pi
// would, so a sandboxed child never needs (or sees) the refresh token. Key-command results are
// cached for the proxy's lifetime (one child run); OAuth results are resolved per request.
//
// Never logs headers, credentials or bodies.
import { createServer, validateHeaderName, validateHeaderValue } from "node:http";
import { request } from "node:https";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

/**
 * Requests in flight at once, per connection and over all connections. Pi's model clients do not
 * pipeline, so a connection with more than this in flight (a flood of pipelined requests, which
 * the HTTP parser would otherwise accept and hold while credentials resolve) is refused and closed.
 */
export const MAX_REQUESTS_PER_CONNECTION = 2;
export const MAX_REQUESTS = 128;

/** Headers the child sends that must not reach the provider: its placeholder credentials. */
const STRIPPED = ["authorization", "x-api-key", "api-key", "proxy-authorization", "cookie", "host", "connection"];

// writeHead can retain framing from earlier headers even when a later header throws.
// Check the entire IncomingMessage header set before touching the guest response.
function validateUpstreamHeaders(status, headers) {
	for (const [name, value] of Object.entries(headers)) {
		validateHeaderName(name);
		for (const item of Array.isArray(value) ? value : [value]) validateHeaderValue(name, item);
	}
	// IncomingMessage normalizes field names to lowercase.
	const length = headers["content-length"];
	const encoding = headers["transfer-encoding"];
	if (length !== undefined && (Array.isArray(length) || !/^\d+$/.test(length) || encoding !== undefined)) {
		throw new Error("invalid upstream content length");
	}
	if (headers.trailer !== undefined && (length !== undefined || !/(?:^|,)\s*chunked\s*$/i.test(encoding ?? "") ||
		status < 200 || status === 204 || status === 304)) {
		throw new Error("invalid upstream trailer framing");
	}
}

/**
 * @param {object} options
 * @param {Record<string, { origin: string }>} options.routes allowlisted providers
 * @param {(provider: string) => Promise<{ apiKey?: string, headers?: Record<string, string>, baseUrl?: string } | undefined>} options.resolveAuth
 * @param {typeof request} [options.forward] HTTPS request function (tests replace it)
 * @param {(line: string) => void} [options.log]
 */
export function createCredentialProxy({ routes, resolveAuth, forward = request, log = (l) => process.stderr.write(`[cred-proxy] ${l}\n`), maxPerConnection = MAX_REQUESTS_PER_CONNECTION, maxRequests = MAX_REQUESTS }) {
	const inFlight = new WeakMap(); // connection -> requests in flight
	let total = 0;
	// Credential resolution outlives a request whose client went away, so it holds its own permit
	// until it settles; requests for the same provider share one resolution in progress.
	let resolving = 0;
	const resolutions = new Map(); // provider -> promise of its credential
	const resolveShared = (name) => {
		if (!resolutions.has(name)) resolutions.set(name, Promise.resolve().then(() => resolveAuth(name)).finally(() => resolutions.delete(name)));
		return resolutions.get(name);
	};
	return createServer(async (req, res) => {
		const conn = req.socket;
		if ((inFlight.get(conn) ?? 0) >= maxPerConnection) {
			// Pipelined past the limit: an answer would queue behind the ones in flight, so close it.
			log("connection_request_limit");
			conn.destroy();
			return;
		}
		if (total >= maxRequests) {
			log("total_request_limit");
			inFlight.set(conn, maxPerConnection); // anything pipelined behind this one is closed, not queued
			res.writeHead(503, { "content-type": "text/plain", connection: "close" }).end("sandbox credential proxy: too many requests in flight\n", () => conn.destroy());
			return;
		}
		inFlight.set(conn, (inFlight.get(conn) ?? 0) + 1);
		total++;
		let released = false;
		let up;
		res.on("close", () => {
			if (!released) {
				released = true;
				total--;
				inFlight.set(conn, Math.max(0, (inFlight.get(conn) ?? 1) - 1));
			}
			// The client went away (or the response ended): no upstream request outlives it.
			up?.destroy();
		});
		const m = /^\/([^/?]+)(\/[^?]*)?(\?.*)?$/.exec(req.url ?? "");
		const name = m?.[1];
		if (!name || !Object.hasOwn(routes, name) || req.method === "CONNECT") {
			log("route_denied");
			res.writeHead(403, { "content-type": "text/plain" }).end("route not allowed by the sandbox policy\n");
			return;
		}
		if (resolving >= maxRequests) {
			log("credential_wait_limit");
			res.writeHead(503, { "content-type": "text/plain", connection: "close" }).end("sandbox credential proxy: too many requests waiting for a credential\n", () => conn.destroy());
			return;
		}
		let auth;
		resolving++;
		try {
			auth = await resolveShared(name);
		} catch {
			log(`credential_resolution_failed provider=${name}`);
			res.writeHead(502, { "content-type": "text/plain" }).end(`sandbox credential proxy: no credential for ${name}\n`);
			return;
		} finally {
			resolving--;
		}
		if (res.destroyed || conn.destroyed) return; // gone while the credential resolved
		// URL and header construction, including synchronous request setup, may throw
		// with host configuration in the diagnostic. Never inspect the exception.
		const upstreamFailed = () => {
			if (res.destroyed || res.writableEnded) return;
			log(`upstream_failed provider=${name}`);
			if (res.headersSent) res.destroy();
			else res.writeHead(502, { "content-type": "text/plain" }).end(`sandbox credential proxy: upstream error for ${name}\n`);
		};
		try {
			if (!auth?.apiKey) {
				log(`credential_missing provider=${name}`);
				res.writeHead(502, { "content-type": "text/plain" }).end(`sandbox credential proxy: no credential for ${name}\n`);
				return;
			}
			const upstream = new URL(routes[name].origin);
			if (auth.baseUrl && new URL(auth.baseUrl).origin !== upstream.origin) {
				log(`credential_endpoint_mismatch provider=${name}`);
				res.writeHead(502, { "content-type": "text/plain" }).end(`sandbox credential proxy: ${name} credential selects another endpoint\n`);
				return;
			}
			// Provider headers from the host models.json (which may carry credentials) are added only here,
			// after the key, so they win as they do in Pi. Names are lower-cased to avoid duplicates.
			const headers = Object.fromEntries(Object.entries(req.headers).filter(([k]) => !STRIPPED.includes(k)));
			headers.authorization = `Bearer ${auth.apiKey}`;
			for (const [k, v] of Object.entries(auth.headers ?? {})) if (k.toLowerCase() !== "host") headers[k.toLowerCase()] = v;
			headers.host = upstream.host;
			up = forward({ hostname: upstream.hostname, port: upstream.port || 443, path: (m[2] ?? "/") + (m[3] ?? ""), method: req.method, headers }, (ur) => {
				ur.on("error", upstreamFailed);
				try {
					const status = ur.statusCode ?? 502;
					validateUpstreamHeaders(status, ur.headers);
					res.writeHead(status, ur.headers);
					ur.pipe(res);
				} catch {
					ur.destroy();
					upstreamFailed();
				}
			});
			up.on("error", upstreamFailed);
			req.pipe(up);
		} catch {
			upstreamFailed();
		}
	});
}

/**
 * Resolve credentials with Pi's ModelRuntime from the Pi install the runner uses, against the
 * host's auth.json and models.json.
 */
export async function piAuthResolver({ piPackageRoot, agentDir }) {
	let runtime;
	const cache = new Map();
	return async (provider) => {
		if (cache.has(provider)) return cache.get(provider);
		runtime ??= await (async () => {
			const { ModelRuntime } = await import(pathToFileURL(join(piPackageRoot, "dist", "index.js")).href);
			return ModelRuntime.create({ authPath: join(agentDir, "auth.json"), modelsPath: join(agentDir, "models.json"), modelsStorePath: join(agentDir, "models-store.json"), refreshOnCreate: false });
		})();
		const result = await runtime.getAuth(provider);
		if (result && result.source !== "OAuth") cache.set(provider, result.auth);
		return result?.auth;
	};
}


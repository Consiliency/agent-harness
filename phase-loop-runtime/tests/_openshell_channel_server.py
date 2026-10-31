"""Child-only synthetic TLS server; stdin EOF stops and stdout acknowledges state."""

import asyncio
import json
import sys

import grpc
import openshell_pb2 as p
import openshell_pb2_grpc as service


async def main():
    reader = asyncio.StreamReader()
    transport, _ = await asyncio.get_running_loop().connect_read_pipe(
        lambda: asyncio.StreamReaderProtocol(reader), sys.stdin)
    server = grpc.aio.server()
    state = dict(calls=0, failure=None, size=0, hold=False)
    events = {name: asyncio.Event() for name in ("entered", "stopped")}

    async def receive(request, context):
        state["calls"] += 1
        if dict(context.invocation_metadata()).get("authorization") != "Bearer synthetic-token":
            await context.abort(grpc.StatusCode.UNAUTHENTICATED, "refused")
        if state["failure"]:
            await context.abort(getattr(grpc.StatusCode, state["failure"]), "refused")
        if state["hold"]:
            events["entered"].set()
            try:
                await asyncio.Event().wait()
            finally:
                events["stopped"].set()

    class Service(service.OpenShellServicer):
        async def ControlCancellationLease(self, request, context):
            await receive(request, context)
            return p.ControlCancellationLeaseResponse()

        async def ExecCancellationLease(self, request, context):
            await receive(request, context)
            yield p.ExecSandboxEvent(stdout={"data": b"x" * state["size"]})

        async def SourceCancellationLease(self, request, context):
            await receive(request, context)
            return p.SourceCancellationLeaseResponse(generation=request.generation)

    try:
        config = json.loads(await reader.readline())
        service.add_OpenShellServicer_to_server(Service(), server)
        if config["plaintext"]:
            port = server.add_insecure_port("127.0.0.1:0")
        else:
            credentials = grpc.ssl_server_credentials([
                (config["key"].encode(), config["cert"].encode())])
            port = server.add_secure_port("127.0.0.1:0", credentials)
        assert port
        await server.start()
        print(json.dumps(dict(port=port)), flush=True)
        while line := await reader.readline():
            command = json.loads(line)
            if "wait" in command:
                await asyncio.wait_for(events[command.pop("wait")].wait(), 5)
            state.update(command)
            print(json.dumps(state), flush=True)
    finally:
        await server.stop(None)
        transport.close()


if __name__ == "__main__":
    asyncio.run(main())

/*
 * The scripted agy stand-in of the strict route conformance suite (AGYROLL §3.4, RECBIND SL-2).
 *
 * It speaks the stream-json surface implied by the redacted qualification record shape:
 * one `init` event, an `agent_response` progress step and one SUCCESS `result` whose last
 * line is a terminal verdict. It holds no raw receipt and makes no network call.
 *
 * Modes are named by the suite's CONFORMANCE_OBLIGATIONS (AGYROLL §3.4, amendments A1 and A2).
 * The suite compiles one binary per control with -DAGY_STANDIN_MODE=<n>. Each mode is a
 * distinct image (distinct bytes, distinct digest), the way a distinct agy release would be:
 *
 *   0 conforming               the reference behaviour; all three operations must pass.
 *   1 no_terminal_event        never emits the terminal `result` event.
 *   2 unregistered_helper      its child execs /usr/bin/sleep, an executable outside the
 *                              registered helper policy.
 *   3 tool_step                its progress step has `step_type` `tool`.
 *   4 ignores_cancel           ignores SIGTERM, SIGINT and SIGHUP; after a SIGTERM it never
 *                              answers and never exits on its own.
 *   5 orphaned_child           leaves a setsid child that ignores SIGTERM and SIGHUP.
 *
 * `--help` and `models` answer like agy, so the owned profile can measure help.
 */
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#ifndef AGY_STANDIN_MODE
#error "AGY_STANDIN_MODE is required"
#endif

#define CONFORMING 0
#define NO_TERMINAL_EVENT 1
#define UNREGISTERED_HELPER 2
#define TOOL_STEP 3
#define IGNORES_CANCEL 4
#define ORPHANED_CHILD 5

/* Long enough that the observer always sees the provider running and its progress. */
#define ANSWER_DELAY_TENTHS 30

static const char INIT[] = "{\"event\":\"init\",\"conversation_id\":\"agy-conformance\"}\n";
static const char PROGRESS[] =
    "{\"event\":\"step_update\",\"conversation_id\":\"agy-conformance\","
    "\"step_update\":{\"step_type\":\"agent_response\",\"conversation_id\":\"agy-conformance\"}}\n";
static const char TOOL[] =
    "{\"event\":\"step_update\",\"conversation_id\":\"agy-conformance\","
    "\"step_update\":{\"step_type\":\"tool\",\"conversation_id\":\"agy-conformance\"}}\n";
static const char RESULT[] =
    "{\"event\":\"result\",\"result\":{\"status\":\"SUCCESS\",\"conversation_id\":\"agy-conformance\","
    "\"response\":\"The stated requirements are internally consistent.\\nAGREE\"}}\n";

static volatile sig_atomic_t terminate_seen = 0;

static void note_terminate(int signum) {
    (void)signum;
    terminate_seen = 1;
}

static void emit(const char *text) {
    size_t left = strlen(text);
    while (left > 0) {
        ssize_t wrote = write(STDOUT_FILENO, text, left);
        if (wrote <= 0) {
            _exit(3);
        }
        text += wrote;
        left -= (size_t)wrote;
    }
}

static int read_request(void) {
    /* The broker writes the sealed prompt as one NDJSON user event. */
    char buffer[1 << 16];
    return fgets(buffer, sizeof buffer, stdin) != NULL && strstr(buffer, "\"event\":\"user\"") != NULL;
}

int main(int argc, char **argv) {
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--help") == 0) {
            emit("Usage: agy [flags]\n  --model <model>\n  --input-format stream-json\n"
                 "  --output-format stream-json\n");
            return 0;
        }
    }
    if (argc > 1 && strcmp(argv[1], "models") == 0) {
        emit("gemini-conformance\tConformance stand-in\n");
        return 0;
    }
    if (AGY_STANDIN_MODE == IGNORES_CANCEL) {
        signal(SIGINT, SIG_IGN);
        signal(SIGHUP, SIG_IGN);
        signal(SIGTERM, note_terminate);
    }
    if (!read_request()) {
        return 2;
    }
    emit(INIT);
    emit(AGY_STANDIN_MODE == TOOL_STEP ? TOOL : PROGRESS);
    if (AGY_STANDIN_MODE == UNREGISTERED_HELPER) {
        pid_t helper = fork();
        if (helper == 0) {
            execl("/usr/bin/sleep", "sleep", "60", (char *)NULL);
            _exit(127);
        }
    }
    if (AGY_STANDIN_MODE == ORPHANED_CHILD) {
        pid_t child = fork();
        if (child == 0) {
            setsid();
            signal(SIGTERM, SIG_IGN);
            signal(SIGHUP, SIG_IGN);
            for (;;) {
                pause();
            }
        }
    }
    for (int i = 0; i < ANSWER_DELAY_TENTHS; i++) {
        usleep(100000);
        while (AGY_STANDIN_MODE == IGNORES_CANCEL && terminate_seen) {
            pause();
        }
    }
    if (AGY_STANDIN_MODE == NO_TERMINAL_EVENT) {
        return 0;
    }
    emit(RESULT);
    return 0;
}

import { EventEmitter } from "events";

/**
 * Fan-out agent events to WS/SSE clients and persist via FastAPI.
 */
export function createEventBus({ api }) {
  const bus = new EventEmitter();
  bus.setMaxListeners(50);
  let runId = null;
  let sequence = 0;

  function setRunId(id) {
    runId = id;
    sequence = 0;
  }

  async function emit(type, payload = {}) {
    sequence += 1;
    const event = {
      type,
      sequence,
      runId,
      createdAt: new Date().toISOString(),
      ...payload,
    };
    bus.emit("event", event);
    if (runId && api) {
      try {
        await api.appendEvent(runId, event);
      } catch (err) {
        console.error("persist event failed:", err.message || err);
      }
    }
    return event;
  }

  return {
    setRunId,
    getRunId: () => runId,
    emit,
    on: (...args) => bus.on(...args),
    off: (...args) => bus.off(...args),
  };
}

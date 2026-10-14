/**
 * Pause the runner until the dashboard answers a question.
 */
export function createInputBroker() {
  const pending = new Map();

  function request(spec) {
    const requestId =
      spec.requestId ||
      `req_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
    return new Promise((resolve, reject) => {
      pending.set(requestId, {
        resolve,
        reject,
        spec: { ...spec, requestId },
        createdAt: Date.now(),
      });
    }).finally(() => {
      pending.delete(requestId);
    });
  }

  function resolve(requestId, answer) {
    const item = pending.get(requestId);
    if (!item) return false;
    item.resolve({ requestId, ...answer });
    pending.delete(requestId);
    return true;
  }

  function reject(requestId, reason) {
    const item = pending.get(requestId);
    if (!item) return false;
    item.reject(new Error(reason || "Input cancelled"));
    pending.delete(requestId);
    return true;
  }

  function listPending() {
    return [...pending.values()].map((p) => p.spec);
  }

  function clearAll(reason = "Run aborted") {
    for (const [id, item] of pending) {
      item.reject(new Error(reason));
      pending.delete(id);
    }
  }

  return { request, resolve, reject, listPending, clearAll };
}

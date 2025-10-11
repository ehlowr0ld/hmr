async function poll() {
  while (true) {
    try {
      const res = await fetch("/---fastapi-reloader---", { method: "HEAD" });
      if (res.ok) {
        break;
      } else if (res.status !== 502) {
        return;
      }
    } catch (error) {}
  }
}

/** @param {Response} response */
async function wait(response) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      return;
    }
    if (value) {
      const chunk = decoder.decode(value, { stream: true });
      if (chunk.includes("1")) {
        return;
      }
    }
  }
}

async function main() {
  const response = await fetch("/---fastapi-reloader---").catch(() => null);
  if (response?.ok && response.body) {
    await wait(response).catch(() => null);
    await poll();
    location.reload();
  } else {
    await poll();
    return await main();
  }
}

if (!window.__fastapi_reloader_loaded) {
  window.__fastapi_reloader_loaded = true;
  main();
}

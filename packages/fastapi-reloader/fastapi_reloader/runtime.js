(async function () {
  const response = await fetch("/---fastapi-reloader---/0");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }
    if (value) {
      const chunk = decoder.decode(value, { stream: true });
      if (chunk.includes("1")) {
        while (true) {
          try {
            const res = await fetch("/---fastapi-reloader---", {
              method: "HEAD",
            });
            if (res.ok) {
              break;
            } else if (res.status !== 502) {
              return;
            }
          } catch (error) {}
        }
        location.reload();
      }
    }
  }
})();

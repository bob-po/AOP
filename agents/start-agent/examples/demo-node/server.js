import http from "node:http";

const port = Number(process.env.PORT || 3000);
const host = process.env.HOST || "0.0.0.0";

const server = http.createServer((req, res) => {
  if (req.url === "/health" || req.url === "/") {
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify({ ok: true, service: "demo-node" }));
    return;
  }
  res.writeHead(404);
  res.end("not found");
});

server.listen(port, host, () => {
  console.log(`demo-node listening on http://${host}:${port}`);
});

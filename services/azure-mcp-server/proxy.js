// Reverse proxy: listens on 0.0.0.0:8080, forwards to azmcp on localhost:5000.
// Starts immediately — returns 503 while azmcp is warming up, then proxies normally.
const http = require('http');
const MCP_PORT = 5000;
const PROXY_PORT = 8080;

http.createServer((req, res) => {
  const opts = {
    hostname: '127.0.0.1',
    port: MCP_PORT,
    path: req.url,
    method: req.method,
    headers: req.headers,
  };
  const p = http.request(opts, (pr) => {
    res.writeHead(pr.statusCode, pr.headers);
    pr.pipe(res);
  });
  p.on('error', () => {
    if (!res.headersSent) res.writeHead(503);
    res.end();
  });
  req.pipe(p);
}).listen(PROXY_PORT, '0.0.0.0', () => {
  console.log('MCP proxy listening on ' + PROXY_PORT);
});

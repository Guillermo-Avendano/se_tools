/**
 * SE ContentEdge Tools — Frontend Server
 * Serves static files and proxies /api to the Python backend.
 */
const express = require('express');
const path = require('path');
const { createProxyMiddleware } = require('http-proxy-middleware');

const app = express();
const PORT = process.env.PORT || 3000;
const API_URL = process.env.API_URL || 'http://localhost:8500';

// Proxy /api to Python backend
app.use('/api', createProxyMiddleware({
    target: API_URL,
    changeOrigin: true,
    pathRewrite: (path) => '/api' + path,
}));

// Serve static files
app.use(express.static(path.join(__dirname, 'public')));

// SPA fallback
app.get('*', (req, res) => {
    res.sendFile(path.join(__dirname, 'public', 'index.html'));
});

app.listen(PORT, () => {
    console.log(`SE ContentEdge Tools UI running at http://localhost:${PORT}`);
    console.log(`  API proxy → ${API_URL}`);
});

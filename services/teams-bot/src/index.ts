import express from "express";
import { loadConfig } from "./config";
import { healthRouter } from "./routes/health";
import { createNotifyRouter } from "./routes/notify";

const config = loadConfig();
const app = express();

app.use(express.json());

// Routes
app.use(healthRouter);
app.use(createNotifyRouter(config));

// Bot messaging endpoint placeholder (wired in Plan 06-02)
// app.post("/api/messages", ...);

app.listen(config.port, () => {
  console.log(`Teams bot listening on port ${config.port}`);
});

export { app }; // For testing

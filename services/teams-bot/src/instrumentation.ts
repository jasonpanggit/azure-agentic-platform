/**
 * OTel auto-instrumentation for teams-bot (D-05).
 * Must be imported BEFORE any other module (loaded via --require or first import in index.ts).
 */
import { useAzureMonitor } from "@azure/monitor-opentelemetry";

const connectionString = process.env.APPLICATIONINSIGHTS_CONNECTION_STRING;

if (connectionString) {
  useAzureMonitor({
    azureMonitorExporterOptions: {
      connectionString,
    },
  });
  console.log("Azure Monitor OpenTelemetry configured for teams-bot");
} else {
  console.warn("APPLICATIONINSIGHTS_CONNECTION_STRING not set — OTel disabled for teams-bot");
}

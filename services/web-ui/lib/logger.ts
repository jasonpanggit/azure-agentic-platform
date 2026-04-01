// Server-side only — do not import in client components

type LogLevel = 'debug' | 'info' | 'warn' | 'error';

const LEVEL_ORDER: Record<LogLevel, number> = {
  debug: 0,
  info: 1,
  warn: 2,
  error: 3,
};

function resolveLogLevel(): LogLevel {
  const env = (process.env.LOG_LEVEL ?? 'info').toLowerCase();
  if (env in LEVEL_ORDER) return env as LogLevel;
  return 'info';
}

interface LogEntry {
  readonly timestamp: string;
  readonly level: LogLevel;
  readonly msg: string;
  readonly service: string;
  readonly [key: string]: unknown;
}

interface Logger {
  debug(msg: string, ctx?: Record<string, unknown>): void;
  info(msg: string, ctx?: Record<string, unknown>): void;
  warn(msg: string, ctx?: Record<string, unknown>): void;
  error(msg: string, ctx?: Record<string, unknown>): void;
  child(ctx: Record<string, unknown>): Logger;
}

function createLogger(baseCtx: Record<string, unknown> = {}): Logger {
  const minLevel = resolveLogLevel();

  function emit(level: LogLevel, msg: string, ctx?: Record<string, unknown>): void {
    if (LEVEL_ORDER[level] < LEVEL_ORDER[minLevel]) return;

    const entry: LogEntry = {
      timestamp: new Date().toISOString(),
      level,
      msg,
      service: 'aap-web-ui',
      ...baseCtx,
      ...ctx,
    };

    const line = JSON.stringify(entry);

    if (level === 'error') {
      console.error(line);
    } else {
      // eslint-disable-next-line no-console
      console.log(line);
    }
  }

  return {
    debug: (msg, ctx?) => emit('debug', msg, ctx),
    info: (msg, ctx?) => emit('info', msg, ctx),
    warn: (msg, ctx?) => emit('warn', msg, ctx),
    error: (msg, ctx?) => emit('error', msg, ctx),
    child: (ctx) => createLogger({ ...baseCtx, ...ctx }),
  };
}

export const logger = createLogger();

export type { Logger, LogLevel };

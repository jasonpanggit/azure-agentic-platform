import { logger } from '../logger';
import type { Logger } from '../logger';

describe('logger', () => {
  let consoleSpy: jest.SpyInstance;
  let consoleErrorSpy: jest.SpyInstance;
  const originalLogLevel = process.env.LOG_LEVEL;

  beforeEach(() => {
    consoleSpy = jest.spyOn(console, 'log').mockImplementation(() => {});
    consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation(() => {});
  });

  afterEach(() => {
    consoleSpy.mockRestore();
    consoleErrorSpy.mockRestore();
    process.env.LOG_LEVEL = originalLogLevel;
  });

  it('emits valid JSON with required fields', () => {
    logger.info('test message');

    expect(consoleSpy).toHaveBeenCalledTimes(1);
    const output = consoleSpy.mock.calls[0][0] as string;
    const parsed = JSON.parse(output);

    expect(parsed).toMatchObject({
      level: 'info',
      msg: 'test message',
      service: 'aap-web-ui',
    });
    expect(parsed.timestamp).toBeDefined();
    expect(new Date(parsed.timestamp).toISOString()).toBe(parsed.timestamp);
  });

  it('routes error level to console.error (stderr)', () => {
    logger.error('failure');

    expect(consoleErrorSpy).toHaveBeenCalledTimes(1);
    expect(consoleSpy).not.toHaveBeenCalled();

    const parsed = JSON.parse(consoleErrorSpy.mock.calls[0][0] as string);
    expect(parsed.level).toBe('error');
    expect(parsed.msg).toBe('failure');
  });

  it('routes info/warn/debug to console.log (stdout)', () => {
    // Force debug level so all levels emit
    process.env.LOG_LEVEL = 'debug';

    // Must re-create logger since LOG_LEVEL is read at creation time
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    jest.resetModules();
    const freshModule = jest.requireActual('../logger') as { logger: Logger };
    const freshLogger = freshModule.logger;

    freshLogger.debug('d');
    freshLogger.info('i');
    freshLogger.warn('w');

    expect(consoleSpy).toHaveBeenCalledTimes(3);
    expect(consoleErrorSpy).not.toHaveBeenCalled();
  });

  it('filters debug messages when LOG_LEVEL is info', () => {
    process.env.LOG_LEVEL = 'info';
    jest.resetModules();
    const freshModule = jest.requireActual('../logger') as { logger: Logger };
    const freshLogger = freshModule.logger;

    freshLogger.debug('should be suppressed');
    freshLogger.info('should appear');

    // debug was suppressed, info was emitted
    expect(consoleSpy).toHaveBeenCalledTimes(1);
    const parsed = JSON.parse(consoleSpy.mock.calls[0][0] as string);
    expect(parsed.msg).toBe('should appear');
  });

  it('filters below warn when LOG_LEVEL is warn', () => {
    process.env.LOG_LEVEL = 'warn';
    jest.resetModules();
    const freshModule = jest.requireActual('../logger') as { logger: Logger };
    const freshLogger = freshModule.logger;

    freshLogger.debug('no');
    freshLogger.info('no');
    freshLogger.warn('yes');
    freshLogger.error('yes');

    expect(consoleSpy).toHaveBeenCalledTimes(1); // warn
    expect(consoleErrorSpy).toHaveBeenCalledTimes(1); // error
  });

  it('child() merges context into every log entry', () => {
    const child = logger.child({ route: '/api/test', request_id: '123' });

    child.info('child message', { extra: true });

    const parsed = JSON.parse(consoleSpy.mock.calls[0][0] as string);
    expect(parsed.route).toBe('/api/test');
    expect(parsed.request_id).toBe('123');
    expect(parsed.extra).toBe(true);
    expect(parsed.msg).toBe('child message');
  });

  it('child() does not modify parent logger context', () => {
    const child = logger.child({ route: '/api/child' });

    logger.info('parent message');
    child.info('child message');

    const parentParsed = JSON.parse(consoleSpy.mock.calls[0][0] as string);
    const childParsed = JSON.parse(consoleSpy.mock.calls[1][0] as string);

    expect(parentParsed.route).toBeUndefined();
    expect(childParsed.route).toBe('/api/child');
  });

  it('includes additional context passed at call site', () => {
    logger.info('with context', { thread_id: 'abc', status: 200 });

    const parsed = JSON.parse(consoleSpy.mock.calls[0][0] as string);
    expect(parsed.thread_id).toBe('abc');
    expect(parsed.status).toBe(200);
  });
});

const baseDir = __dirname;

module.exports = {
  apps: [
    {
      name: 'driftgauge',
      cwd: baseDir,
      script: `${baseDir}/.venv/bin/uvicorn`,
      args: 'app.main:app --host 127.0.0.1 --port 8030',
      interpreter: 'none',
      autorestart: true,
      watch: false,
      env: {
        PYTHONUNBUFFERED: '1',
        DRIFTGAUGE_DB_PATH: process.env.DRIFTGAUGE_DB_PATH || `${baseDir}/driftgauge.db`,
        RESEND_API_KEY: process.env.RESEND_API_KEY || '',
        DRIFTGAUGE_EMAIL_FROM: process.env.DRIFTGAUGE_EMAIL_FROM || 'Driftgauge <alerts@example.com>',
      },
    },
  ],
};

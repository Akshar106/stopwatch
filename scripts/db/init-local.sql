-- Local development only: mirrors the Neon setup (owner role runs migrations, app role runs the API/jobs).
create role stopwatch_app_role nologin;
create role stopwatch_app login password 'app-local-only';
grant stopwatch_app_role to stopwatch_app;

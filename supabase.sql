-- Radar Nocturno · estados compartidos
-- Pegar tal cual en Supabase → SQL Editor → Run

create table if not exists radar_estados (
  app        text        not null,           -- 'mapa' o 'tracker'
  id         text        not null,           -- id del negocio/prospecto
  data       jsonb       not null,           -- {e, n, h?} tal como lo usa cada página
  updated_at timestamptz not null default now(),
  primary key (app, id)
);

create or replace function radar_touch() returns trigger as $$
begin new.updated_at = now(); return new; end;
$$ language plpgsql;

drop trigger if exists radar_estados_touch on radar_estados;
create trigger radar_estados_touch before update on radar_estados
  for each row execute function radar_touch();

alter table radar_estados enable row level security;

-- Acceso con la anon key (la protección de la página es el RADAR_TOKEN del server)
drop policy if exists "radar rw anon" on radar_estados;
create policy "radar rw anon" on radar_estados
  for all using (true) with check (true);

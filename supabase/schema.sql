-- Shared feedback and results for One-Pot Puzzles and Name Reaction Daily.
-- Run once in the Supabase SQL editor (Dashboard -> SQL Editor -> New query -> paste -> Run).
-- Visitors use the public anon key: they can insert their own row once per problem and read
-- only aggregates. Remarks are readable through feedback_export() so the scheduled tasks can
-- use them without a secret key; do not treat remarks as private.

create table if not exists public.results (
  id          bigint generated always as identity primary key,
  site        text        not null check (site in ('onepot', 'namerxn')),
  problem_id  text        not null check (char_length(problem_id) between 1 and 120),
  client_id   uuid        not null,
  checks      smallint    not null check (checks between 0 and 999),
  hints       smallint    not null check (hints between 0 and 30),
  score       smallint    not null check (score between 0 and 2000),
  revealed    boolean     not null,
  created_at  timestamptz not null default now(),
  unique (site, problem_id, client_id)
);

create table if not exists public.ratings (
  id          bigint generated always as identity primary key,
  site        text        not null check (site in ('onepot', 'namerxn')),
  problem_id  text        not null check (char_length(problem_id) between 1 and 120),
  client_id   uuid        not null,
  stars       smallint    not null check (stars between 1 and 5),
  remark      text        check (remark is null or char_length(remark) <= 1000),
  created_at  timestamptz not null default now(),
  unique (site, problem_id, client_id)
);

alter table public.results enable row level security;
alter table public.ratings enable row level security;

-- Insert only; no direct select, update or delete for visitors.
drop policy if exists results_insert on public.results;
create policy results_insert on public.results for insert to anon, authenticated with check (true);
drop policy if exists ratings_insert on public.ratings;
create policy ratings_insert on public.ratings for insert to anon, authenticated with check (true);

revoke all on public.results, public.ratings from anon, authenticated;
grant insert (site, problem_id, client_id, checks, hints, score, revealed) on public.results to anon, authenticated;
grant insert (site, problem_id, client_id, stars, remark) on public.ratings to anon, authenticated;

-- Aggregates for one problem: score distribution of solvers, revealed count, rating summary.
create or replace function public.problem_stats(p_site text, p_problem text)
returns json language sql stable security definer set search_path = public as $$
  select json_build_object(
    'solved',   (select coalesce(json_object_agg(score, n), '{}'::json)
                 from (select score, count(*) n from results
                       where site = p_site and problem_id = p_problem and not revealed
                       group by score) s),
    'revealed', (select count(*) from results where site = p_site and problem_id = p_problem and revealed),
    'ratings',  (select json_build_object('n', coalesce(sum(n), 0),
                        'mean', round(sum(stars * n)::numeric / nullif(sum(n), 0), 2),
                        'dist', coalesce(json_object_agg(stars, n), '{}'::json))
                 from (select stars, count(*) n from ratings
                       where site = p_site and problem_id = p_problem group by stars) r)
  );
$$;

-- Ratings and remarks since a date, with the result of the same visitor when present.
-- Used by the scheduled tasks; readable by anyone holding the anon key.
create or replace function public.feedback_export(p_site text, p_since timestamptz default now() - interval '120 days')
returns table (problem_id text, stars smallint, remark text, created_at timestamptz,
               score smallint, revealed boolean)
language sql stable security definer set search_path = public as $$
  select r.problem_id, r.stars, r.remark, r.created_at, x.score, x.revealed
  from ratings r
  left join results x on x.site = r.site and x.problem_id = r.problem_id and x.client_id = r.client_id
  where r.site = p_site and r.created_at >= p_since
  order by r.created_at;
$$;

-- Per-problem summary (all problems), for the scheduled tasks.
create or replace function public.problem_summary(p_site text)
returns table (problem_id text, n_results bigint, n_revealed bigint, median_score numeric,
               n_ratings bigint, mean_stars numeric)
language sql stable security definer set search_path = public as $$
  with ids as (select problem_id from results where site = p_site
               union select problem_id from ratings where site = p_site)
  select i.problem_id,
         (select count(*) from results x where x.site = p_site and x.problem_id = i.problem_id),
         (select count(*) from results x where x.site = p_site and x.problem_id = i.problem_id and x.revealed),
         (select percentile_cont(0.5) within group (order by x.score)::numeric from results x
          where x.site = p_site and x.problem_id = i.problem_id and not x.revealed),
         (select count(*) from ratings r where r.site = p_site and r.problem_id = i.problem_id),
         (select round(avg(r.stars)::numeric, 2) from ratings r where r.site = p_site and r.problem_id = i.problem_id)
  from ids i order by i.problem_id;
$$;

revoke all on function public.problem_stats(text, text), public.feedback_export(text, timestamptz),
  public.problem_summary(text) from public;
grant execute on function public.problem_stats(text, text), public.feedback_export(text, timestamptz),
  public.problem_summary(text) to anon, authenticated;

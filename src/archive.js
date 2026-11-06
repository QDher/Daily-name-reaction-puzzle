// archive.js — sets older than ARCHIVE_AFTER_DAYS move from data/problems.json to data/archive.json.gz
// (gzip of {"sets": [...]}, ascending dates). The page embeds only data/problems.json, so visitors can open
// the last month of sets; archived sets stay available to the scripts (ids, papers and reactions already used).
// build.js calls archiveOldSets(); validate_problems.js reads readArchive().
const fs = require('fs');
const path = require('path');
const zlib = require('zlib');

const ARCHIVE_AFTER_DAYS = 32;   // the page lists the last 31 days; one day of margin
const root = path.join(__dirname, '..');
const ARCHIVE = path.join(root, 'data', 'archive.json.gz');

function readArchive() {
  if (!fs.existsSync(ARCHIVE)) return [];
  return JSON.parse(zlib.gunzipSync(fs.readFileSync(ARCHIVE)).toString('utf8')).sets || [];
}

// today's date (YYYY-MM-DD) as a wall-clock date in the schedule's time zone
function todayIn(timeZone, now = Date.now()) {
  return new Intl.DateTimeFormat('en-CA', { timeZone, year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(now));
}

// Moves old sets into the archive; returns the number of sets moved. Rewrites both files only when something moved.
function archiveOldSets(problemsFile, now = Date.now()) {
  const data = JSON.parse(fs.readFileSync(problemsFile, 'utf8'));
  const tz = (data.schedule && data.schedule.timeZone) || 'America/New_York';
  const t = new Date(todayIn(tz, now) + 'T00:00:00Z');
  const cutoff = new Date(t.getTime() - ARCHIVE_AFTER_DAYS * 864e5).toISOString().slice(0, 10);
  const old = data.sets.filter(s => s.date < cutoff);
  if (!old.length) return 0;
  const byDate = new Map(readArchive().map(s => [s.date, s]));
  old.forEach(s => byDate.set(s.date, s));
  const sets = [...byDate.values()].sort((a, b) => (a.date < b.date ? -1 : 1));
  fs.writeFileSync(ARCHIVE, zlib.gzipSync(Buffer.from(JSON.stringify({ sets }), 'utf8'), { level: 9 }));
  data.sets = data.sets.filter(s => s.date >= cutoff);
  fs.writeFileSync(problemsFile, JSON.stringify(data, null, 2) + '\n');
  return old.length;
}

module.exports = { ARCHIVE_AFTER_DAYS, readArchive, archiveOldSets, todayIn };

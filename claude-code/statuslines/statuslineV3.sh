#!/bin/bash
# Custom Claude Code statusline

input=$(cat)

# ---- options ----
short_dir=1  # 1 = show only parent/current, 0 = show full path

# ---- colors ----
use_color=1
[ -n "$NO_COLOR" ] && use_color=0

dir_color() { if [ "$use_color" -eq 1 ]; then printf '\033[0;38;5;117m'; fi; }     # sky blue
model_color() { if [ "$use_color" -eq 1 ]; then printf '\033[0;38;5;147m'; fi; }   # light purple
version_color() { if [ "$use_color" -eq 1 ]; then printf '\033[0;38;5;186m'; fi; } # soft yellow
sep_color() { if [ "$use_color" -eq 1 ]; then printf '\033[0;38;5;249m'; fi; }     # light gray
style_color() { if [ "$use_color" -eq 1 ]; then printf '\033[0;38;5;245m'; fi; }   # gray
ram_color() { if [ "$use_color" -eq 1 ]; then printf '\033[0;38;5;218m'; fi; }     # pastel pink
ctx_color() { if [ "$use_color" -eq 1 ]; then printf '\033[0;38;5;116m'; fi; }     # soft teal
dur_color() { if [ "$use_color" -eq 1 ]; then printf '\033[0;38;5;173m'; fi; }     # muted salmon
git_color() { if [ "$use_color" -eq 1 ]; then printf '\033[0;38;5;150m'; fi; }     # soft green
cost_color() { if [ "$use_color" -eq 1 ]; then printf '\033[0;38;5;222m'; fi; }    # light gold
session_color() { if [ "$use_color" -eq 1 ]; then printf '\033[0;38;5;194m'; fi; } # light green
rst() { if [ "$use_color" -eq 1 ]; then printf '\033[0m'; fi; }

# ---- parse JSON input ----
if command -v jq >/dev/null 2>&1; then
  has_jq=1
  current_dir=$(echo "$input" | jq -r '.workspace.current_dir // .cwd // "unknown"' 2>/dev/null | sed "s|^$HOME|~|g")
  model_name=$(echo "$input" | jq -r '.model.display_name // "Claude"' 2>/dev/null)
  cc_version=$(echo "$input" | jq -r '.version // ""' 2>/dev/null)
  # output_style=$(echo "$input" | jq -r '.output_style.name // ""' 2>/dev/null)
  # .effort.level is absent (not null) when the model doesn't support effort
  effort_level=$(echo "$input" | jq -r '.effort.level // ""' 2>/dev/null)
  ctx_pct=$(echo "$input" | jq -r '.context_window.used_percentage // 0' 2>/dev/null | cut -d. -f1)
  total_cost=$(printf '%.2f' "$(echo "$input" | jq -r '.cost.total_cost_usd // 0' 2>/dev/null)")
  total_dur_ms=$(echo "$input" | jq -r '.cost.total_duration_ms // 0' 2>/dev/null)
  # rate limits: 5-hour + 7-day usage %
  rl_5h_pct=$(echo "$input" | jq -r '.rate_limits.five_hour.used_percentage // ""' 2>/dev/null | cut -d. -f1)
  rl_7d_pct=$(echo "$input" | jq -r '.rate_limits.seven_day.used_percentage // ""' 2>/dev/null | cut -d. -f1)
else
  has_jq=0
  current_dir="unknown"
  model_name="Claude"
  cc_version=""
  # output_style=""
  effort_level=""
  ctx_pct=0
  total_cost="0.00"
  total_dur_ms=0
  rl_5h_pct=""
  rl_7d_pct=""
fi

# ---- shorten model name ----
# drop a trailing " context" so "Opus 4.8 (1M context)" reads "Opus 4.8 (1M)"
model_name=${model_name/ context/}

# ---- shorten directory ----
if [ "$short_dir" -eq 1 ] && [ "$current_dir" != "unknown" ]; then
  parent_dir=$(dirname "$current_dir")
  base_dir=$(basename "$current_dir")
  case "$parent_dir" in
    "."|"/"|"~") : ;;  # already at root/home; leave as-is
    *) current_dir="$(basename "$parent_dir")/$base_dir" ;;
  esac
fi

# ---- format duration ----
total_dur_sec=$(( total_dur_ms / 1000 ))
dur_days=$(( total_dur_sec / 86400 ))
dur_hours=$(( (total_dur_sec % 86400) / 3600 ))
dur_mins=$(( (total_dur_sec % 3600) / 60 ))
dur_txt=""
if (( total_dur_sec < 60 )); then
  dur_txt="${total_dur_sec}s"
elif (( dur_days > 0 )); then
  dur_txt="${dur_days}d ${dur_hours}h"
elif (( dur_hours > 0 )); then
  dur_txt="${dur_hours}h ${dur_mins}m"
else
  dur_txt="${dur_mins}m"
fi

# ---- git ----
git_branch="no git"
if git rev-parse --git-dir >/dev/null 2>&1; then
  git_branch=$(git branch --show-current 2>/dev/null || git rev-parse --short HEAD 2>/dev/null)
fi

# ---- session / rate limits ----
# format: "5h 13% | 7d 7%"
session_txt=""
if [ -n "$rl_5h_pct" ] || [ -n "$rl_7d_pct" ]; then
  [ -n "$rl_5h_pct" ] && session_txt="${session_txt:+$session_txt | }5h ${rl_5h_pct}%"
  [ -n "$rl_7d_pct" ] && session_txt="${session_txt:+$session_txt | }7d ${rl_7d_pct}%"
  session_txt="$session_txt "
fi

# ---- ram usage ----
proc_name="claude"
pids_name=$(pgrep -x "$proc_name" 2>/dev/null || true)
pids_path=$(pgrep -fx ".*/${proc_name}([[:space:]].*)?$" 2>/dev/null || true)

ppid=$(ps -o ppid= -p "$$" 2>/dev/null | tr -d ' ' || true)
ppid_match=""
if [ -n "$ppid" ]; then
  parent_cmd=$(ps -o command= -p "$ppid" 2>/dev/null || ps -o comm= -p "$ppid" 2>/dev/null || true)
  if printf '%s' "$parent_cmd" | grep -Eq "(^|/|[[:space:]])${proc_name}([[:space:]]|$)"; then
    ppid_match="$ppid"
  fi
fi

pids=$(printf '%s\n%s\n%s\n' "$pids_name" "$pids_path" "$ppid_match" | awk 'NF{seen[$1]++} END{for (p in seen) print p}')

if [ -z "$pids" ]; then
  ram_usage="RAM: 0.0MB (0 | 0.0%)"
else
  pidlist=$(echo "$pids" | paste -sd, -)
  num_procs=$(echo "$pids" | wc -l | tr -d ' ')
  ram_usage=$(LC_ALL=C ps -o %mem=,rss= -p "$pidlist" 2>/dev/null | \
    awk -v count="$num_procs" 'NF{mem+=$1; rss+=$2; found++}
         END{
           if (found==0) {printf "RAM: 0.0MB (0 | 0.0%%)"}
           else {
             mb = rss/1024
             if (mb >= 1000) printf "RAM: %.2fGB (%d | %.1f%%)", mb/1024, found, mem
             else            printf "RAM: %.1fMB (%d | %.1f%%)", mb, found, mem
           }
         }')
fi

# ---- render statusline ----
# line 1: directory, git, model, effort, cc version
printf '%s%s%s' "$(dir_color)" "$current_dir" "$(rst)"
printf ' %s✦ %s%s%s' "$(sep_color)" "$(git_color)" "$git_branch" "$(rst)"
printf ' %s✦ %s%s%s' "$(sep_color)" "$(model_color)" "$model_name" "$(rst)"
# if [ -n "$output_style" ] && [ "$output_style" != "null" ]; then
#   printf ' %s✦ %s%s%s' "$(sep_color)" "$(version_color)" "$output_style" "$(rst)"
# fi
if [ -n "$effort_level" ] && [ "$effort_level" != "null" ]; then
  printf ' %s✦ %s%s%s' "$(sep_color)" "$(version_color)" "$effort_level" "$(rst)"
fi
if [ -n "$cc_version" ] && [ "$cc_version" != "null" ]; then
  printf ' %s✦ %s%sv%s%s' "$(sep_color)" "$(rst)" "$(style_color)" "$cc_version" "$(rst)"
fi

# line 2: session, ram, context, cost, duration
printf '\n '
if [ -n "$session_txt" ]; then
  printf '%s%s%s' "$(session_color)" "$session_txt" "$(rst)"
else
  printf '%sNo ongoing session%s ' "$(session_color)" "$(rst)"
fi
printf '%s✦ %s%s%s' "$(sep_color)" "$(ram_color)" "$ram_usage" "$(rst)"
printf ' %s✦ %s%s%% ctx%s' "$(sep_color)" "$(ctx_color)" "$ctx_pct" "$(rst)"
printf ' %s✦ %s$%s%s' "$(sep_color)" "$(cost_color)" "$total_cost" "$(rst)"
printf ' %s✦ %s%s%s' "$(sep_color)" "$(dur_color)" "$dur_txt" "$(rst)"
printf '\n'

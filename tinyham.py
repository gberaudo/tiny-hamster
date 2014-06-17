#!/usr/bin/env python
# -*- coding: UTF-8 -*-

import datetime
import pytz
import sys
import csv
import os

try:
    from pysqlite2 import dbapi2 as sqlite
except ImportError:
    import sqlite3 as sqlite

import tinylib
try:
    import tinyconf
except ImportError:
    print ("No configuration file found. You have to copy "
           "'tinyconf.py.example' to 'tinyconf.py' and change the options.")
    exit(1)

if len(sys.argv) > 1:
  date = sys.argv[1]
else:
  date = datetime.datetime.today().strftime("%Y-%m-%d")

con = sqlite.connect(os.path.expanduser("~/.local/share/hamster-applet/hamster.db"))
cur = con.cursor()

activities = {}

cur.execute("""
SELECT start_time, end_time, activities.name, description, categories.name, tags.name
FROM facts
LEFT JOIN activities ON facts.activity_id=activities.id
LEFT JOIN categories ON activities.category_id=categories.id
LEFT JOIN fact_tags  ON facts.id=fact_tags.fact_id
LEFT JOIN tags       ON fact_tags.tag_id = tags.id
WHERE date(start_time)="%s" ORDER BY start_time;
""" %(date))

## TinyERP ##
try:
    tiny = tinylib.TinyServer(tinyconf.user_name, tinyconf.user_pwd, tinyconf.tiny_db, tinyconf.rpc_url)
except:
    print "Failed to connect to openerp... is it up?"
    print "ping ", tinyconf.rpc_url
    exit(1)

ts_def = tiny.timesheet_defaults()
att_def = tiny.attendance_defaults()


att_lines = []
last_end_time = None
last_end_str = None
to_s = lambda d: d.strftime('%Y-%m-%d %H:%M:%S')
to_utc = lambda d: to_s(d.astimezone(pytz.utc))
p_date = lambda dstr: datetime.datetime.strptime(dstr, "%Y-%m-%d %H:%M:%S")

for r in cur:
  start_time_str, end_time_str, activity, description, category, tag = r

  if end_time_str is None:
    print "There is an unfinished activity, can't timesheet that, sorry!"
    sys.exit(1)

  start_time = p_date(start_time_str)
  end_time = p_date(end_time_str)
  start_time = pytz.timezone("Europe/Paris").localize(start_time, is_dst=None)
  end_time = pytz.timezone("Europe/Paris").localize(end_time, is_dst=None)

  duration = end_time - start_time

  if activity in activities:
    activities[activity][0] += duration
  else:
    activities[activity] = [duration, category, tag]
 
  if last_end_time is None or last_end_time != start_time:
      if last_end_time is not None:
        att_lines.append([0, 0, {"action": "sign_out", "employee_id": att_def["employee_id"], "name": "%s" %(to_utc(last_end_time))}])
      att_lines.append([0, 0, {"action": "sign_in", "employee_id": att_def["employee_id"], "name": "%s" %(to_utc(start_time))}])
  
  last_end_time = end_time

cur.close()

if not activities:
  print "No activity registered for that day. Nothing to do."
  sys.exit()

att_lines.append([0, 0, {"action": "sign_out", "employee_id": att_def["employee_id"], "name": "%s" %(to_utc(last_end_time))}])


day_total = sum([infos[0] for infos in activities.values()], datetime.timedelta())


ts_lines = []

last_end=0
for activity, infos in activities.items():
  duration, category, tag = infos #, tiny_activity = infos
  duration_hours = duration.seconds/3600.0

  if category is None:
    print "Category missing for '%s'. Please fix." %(activity)
    sys.exit(1)

  if duration_hours == 0:
    print "Activity '%s' has zero duration. Please fix." %(activity)
    sys.exit(1)
 
  match_acc = tiny.search_account(category)
  if len(match_acc) == 0:
    print "No account found for '%s' in OpenERP. Please fix." %(category)
    sys.exit(1)
  elif len(match_acc) > 1:
    names = [ma[1] for ma in match_acc]
    if category in names:
      acc_id, acc_name = match_acc[names.index(category)]
    else:
      print "Multiple accounts found for '%s' in OpenERP. Please fix." %(category)
      sys.exit(1)
  else:
    acc_id, acc_name = match_acc[0]

  if tag is None:
    task_id = None
  else:
    match_task = tiny.search_task(acc_id, tag)
    if len(match_task) == 0:
      print "No task found for '%s' in account '%s' in OpenERP. Please fix." %(tag, category)
      sys.exit(1)
    elif len(match_task) > 1:
      print "Multiple tasks found for '%s' in account '%s' in OpenERP. Please fix." %(tag, category)
      sys.exit(1)
    else:
      task_id = match_task[0]

  #act_id, act_name = tiny.search_activity(acc_id, tiny_activity)[0]
  to_invoice = tiny.on_change_account_id(acc_id)["value"]["to_invoice"]
  amount = tiny.on_change_unit_amount(ts_def["product_id"], duration_hours, ts_def["product_uom_id"])["value"]["amount"]

  ts_line_infos = {"user_id": tiny.user_id,
                   "name": activity,
                   "general_account_id": ts_def["general_account_id"],
                   "product_uom_id": ts_def["product_uom_id"],
                   "journal_id": ts_def["journal_id"],
                   "to_invoice": to_invoice,
                   "amount": amount,
                   "product_id": ts_def["product_id"],
                   "unit_amount": duration_hours,
                   #"activity": act_id,
                   "date": date,
                   "account_id": acc_id}
  if task_id:
    ts_line_infos["task_id"] = task_id

  ts_lines.append([0, 0, ts_line_infos])

#ts_id = tiny.current_timesheet_wiz()["action"]["res_id"]
ts_id = tiny.search_timesheet(date)[0]

tiny.timesheet_write(ts_id, ts_lines, att_lines)

print "Timesheet done."

# show tables
#cur = con.cursor()
#cur.execute("select * from sqlite_master;")
#for r in cur:
#  if r[0] == "table":
#    print r[1], r[4]

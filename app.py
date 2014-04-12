#!flask/bin/python
from flask import Flask, jsonify, request
import gdata.calendar.data
import gdata.calendar.client
import gdata.calendar.service
import gdata.acl.data
import string
import sys
import datetime
import time
import atom
import ast
import xmltodict
import json

app = Flask(__name__)


# helper functions

def normalize_time(datetime_string):
    datetime_string = (datetime.datetime.strptime(datetime_string, "%Y-%m-%dT%H:%M:%S.000Z") + datetime.timedelta(hours=8)).strftime("%Y-%m-%dT%H:%M:%S.000+08:00")
    return datetime_string

def string_to_time(datetime_string):
    if datetime_string is '':
        return None
    return datetime.datetime.strptime(datetime_string, "%Y-%m-%dT%H:%M:%S.000+08:00")

def date_only(datetime_string):
    return '-' in datetime_string and ':' not in datetime_string

def time_only(datetime_string):
    return ':' in datetime_string and '-' not in datetime_string

def date_and_time(datetime_string):
    return 'T' in datetime_string

def init(local_auth):
    username = local_auth['username']
    password = local_auth['password']
    client = gdata.calendar.client.CalendarClient(source='Todomato')

    client.ClientLogin(username, password, client.source)
    feed = client.GetAllCalendarsFeed()
   
    cid = None
    cal_url = None

    # create or get todomato calendar list
    for i, cal in zip(xrange(len(feed.entry)), feed.entry):
        if cal.title.text == "Todomato":
            cal_url = cal.id.text
            print 'new calendar created: No'
    if cal_url is None:
        print 'new calendar created: Yes'
        calendar = gdata.calendar.data.CalendarEntry()
        calendar.title = atom.data.Title(text="Todomato")
        calendar.timezone = gdata.calendar.data.TimeZoneProperty(value="Asia/Singapore")
        cal_url = client.InsertCalendar(new_calendar=calendar).id.text

    cid = cal_url.split("http://www.google.com/calendar/feeds/default/calendars/")[1]
    feed_uri = "http://www.google.com/calendar/feeds/%s/private/full" %(cid,)
    
    # get calendar events
    remote_tasklist = get_remote_tasks(client, feed_uri)

    return remote_tasklist, client, feed_uri

def update(client, feed_uri, local_tasklist, remote_tasklist, last_sync, time_offset):

    if len(local_tasklist) == 0 and last_sync is '':
        local_tasklist = remote_tasklist
        return local_tasklist
    elif len(remote_tasklist) == 0 and last_sync is '':
        remote_tasklist = create_remote_tasks(client, feed_uri, local_tasklist)
        local_tasklist = remote_tasklist
        return local_tasklist
    else:
        
        for i in range(0, len(local_tasklist)):
            task = local_tasklist[i]
            last_sync_time = string_to_time(last_sync)
            last_sync_time = last_sync_time - time_offset

        # local create
            if 'eid' not in task or last_sync_time is None:
                updated_task = create_remote_task(client, feed_uri, task)
                local_tasklist[i] = updated_task
                print "local create, sync at remote: ", task['description'] , ' created'
            else:
                eid = task['eid']
                event = get_event_by_eid(remote_tasklist, eid)
                local_updated_time = string_to_time(task['edit']) - time_offset
        # remote delete
                if event is None and local_updated_time < last_sync_time:
                    local_tasklist[i] = None
                    print "remote delete, sync at local: ", task['description'], ' deleted'
                elif event is not None:
                    remote_updated_time = string_to_time(event['edit'])
        # local or remote update

                    if local_updated_time > last_sync_time or remote_updated_time > last_sync_time:
                        if local_updated_time > remote_updated_time:
                            local_tasklist[i] = update_remote_task(client, feed_uri, eid, task)
                            print "local update, sync at remote: ", task['description'], ' updated'
                        elif local_updated_time < remote_updated_time:
                            local_tasklist[i] = event
                            print "remote update, sync at local: ", task['description'], ' updated'

        
        for event in remote_tasklist:
            eid = event['eid']
            remote_updated_time = string_to_time(event['edit'])
            local_task = get_event_by_eid(local_tasklist, eid)
            if local_task is None:
                last_sync_time = string_to_time(last_sync)
        # remote create

                if last_sync_time is None or remote_updated_time > last_sync_time:
                    local_tasklist.append(event)
                    print "remote create, sync at local: ", event['description'], ' created'
        # local detele      
                else:
                    event_uri = feed_uri + '/' + eid[-26:]
                    event = client.get_calendar_entry(event_uri, desired_class=gdata.calendar.data.CalendarEventEntry)
                    client.Delete(event)
                    print "local delete, sync at remote: ", event['description'], ' deleted'

        local_tasklist = [t for t in local_tasklist if t is not None]

        return local_tasklist

def get_event_by_eid(tasklist, eid):
    for event in tasklist:
        if event is not None and event['eid'] == eid:
            return event
    return None

def event_to_json(event):
    xmlstring = event.ToString()
    xml_dict = xmltodict.parse(xmlstring, process_namespaces=True)
    edit_time = normalize_time(xml_dict['http://www.w3.org/2005/Atom:entry']['http://www.w3.org/2005/Atom:updated'])
    created_time = normalize_time(xml_dict['http://www.w3.org/2005/Atom:entry']['http://www.w3.org/2005/Atom:published'])

    if (event.content.text is None):
        timecode = '1111'
        id = None
        priority = "LOW"
        completed = "false"
    else:
        meta = eval(event.content.text)
        timecode = meta['timecode']
        id = meta['id']
        priority = meta['priority']
        completed = meta['completed']

    start = event.when[0].start
    end = event.when[0].end
    startdate = start.split('T')[0]
    enddate = end.split('T')[0]
    starttime = ""
    endtime = ""

    if date_and_time(start) and date_and_time(end):
        starttime = start.split('T')[1]
        endtime = end.split('T')[1]

    time = [startdate, starttime, enddate, endtime]
    has_start_date = (timecode[0] == '1')
    has_start_time = (timecode[1] == '1')
    has_end_date = (timecode[2] == '1')
    has_end_time = (timecode[3] == '1')

    if not has_start_date:
        startdate = ""
    if not has_start_time:
        starttime = ""
    if not has_end_date:
        enddate = ""
    if not has_end_time:
        endtime = ""


    event_dict = {
            'meta':{
                'id':id,
                'priority':priority,
                'completed':completed,
                'timecode':timecode,
            },
            'eid': event.id.text,
            'description':event.title.text,
            'startdate':startdate,
            'starttime':starttime,
            'enddate':enddate,
            'endtime':endtime,
            'location':event.where[0].value,
            'edit': edit_time,
            'created': created_time,
        }

    print json.dumps(event_dict, sort_keys=True, indent=4)

    return event_dict

def get_remote_tasks(client, feed_uri):
    feed = client.GetCalendarEventFeed(uri=feed_uri)
    remote_tasklist = []
    for i, event in zip(xrange(len(feed.entry)), feed.entry):
        event_dict = event_to_json(event)
        remote_tasklist.append(event_dict)
    return remote_tasklist

def create_remote_tasks(client, feed_uri, local_tasklist):
    for task in local_tasklist:
        create_remote_task(client, feed_uri, task)
    remote_tasklist = get_remote_tasks(client, feed_uri)
    return remote_tasklist

def process_datetime_from_timecode(task):\

    timecode = task['meta']['timecode']

    has_start_date = (timecode[0] == '1')
    has_start_time = (timecode[1] == '1')
    has_end_date = (timecode[2] == '1')
    has_end_time = (timecode[3] == '1')

    starttime = task['starttime']
    endtime = task['endtime']
    startdate = task['startdate']
    enddate = task['enddate']

    if starttime is not "":
        starttime_dt = datetime.datetime.strptime(starttime[:5], "%H:%M")
    else:
        starttime_dt = None

    if startdate is not "":
        startdate_dt = datetime.datetime.strptime(startdate[:10], "%Y-%m-%d")
    else:
        startdate_dt = None

    if endtime is not "":
        endtime_dt = datetime.datetime.strptime(endtime[:5], "%H:%M")
    else:
        endtime_dt = None

    if enddate is not "":
        enddate_dt = datetime.datetime.strptime(enddate[:10], "%Y-%m-%d")
    else:
        enddate_dt = None


    # process data

    # 1111
    if has_start_date and has_start_time and has_end_date and has_end_time:
        pass
    # 1101
    elif has_start_date and has_start_time and has_end_date and not has_end_date:
        if starttime_dt > endtime_dt:
            enddate = startdate_dt.timedelta + datetime.timedelta(days=1)
        else:
            enddate = startdate

    # 1110
    elif has_start_date and has_start_time and has_end_date and not has_end_time:
        endtime = starttime

    # 1011
    elif has_start_date and not has_start_time and has_end_date and has_end_time:
        starttime = endtime

    # 0111
    elif not has_start_date and has_start_time and has_end_date and has_end_time:
        if starttime_dt > endtime_dt:
            startdate = enddate_dt.timedelta - datetime.timedelta(days=1)
        else:
            startdate = enddate

    # 1100
    elif has_start_date and has_start_time and not has_end_date and not has_end_time:
        enddate = startdate
        endtime = starttime

    # 0101
    elif not has_start_date and has_start_time and not has_end_date and has_end_time:
        startdate = (datetime.datetime.now() + datetime.timedelta(hours=8)).strftime("%Y-%m-%d")
        enddate = startdate

    # 0110
    elif not has_start_date and has_start_time and has_end_date and not has_end_time:
        startdate = enddate
        endtime = starttime

    # 1001
    elif has_start_date and not has_start_time and not has_end_date and has_end_time:
        enddate = startdate
        starttime = endtime

    # 1010
    elif has_start_date and not has_start_time and has_end_date and not has_end_time:
        pass

    # 0011
    elif not has_start_date and not has_start_time and has_end_date and has_end_time:
        starttime = endtime
        startdate = enddate

    # 0100
    elif not has_start_date and has_start_time and not has_end_date and not has_end_time:
        endtime = starttime
        startdate = (datetime.datetime.now() + datetime.timedelta(hours=8)).strftime("%Y-%m-%d")
        enddate = startdate

    # 1000
    elif has_start_date and not has_start_time and not has_end_date and not has_end_time:
        enddate = startdate
        startdate = (datetime.datetime.now() + datetime.timedelta(hours=8)).strftime("%Y-%m-%d")
        enddate = startdate

    # 0001
    elif not has_start_date and not has_start_time and not has_end_date and has_end_time:
        starttime = endtime
        enddate = startdate = (datetime.datetime.now() + datetime.timedelta(hours=8)).strftime("%Y-%m-%d")

    # 0010
    elif not has_start_date and not has_start_time and has_end_date and not has_end_time:
        enddate = startdate = (datetime.datetime.now() + datetime.timedelta(hours=8)).strftime("%Y-%m-%d")
    # 0000
    else:
        enddate = startdate = (datetime.datetime.now() + datetime.timedelta(hours=8)).strftime("%Y-%m-%d")

    if starttime == "" or endtime == "":
        start = startdate
        end = enddate
    else:
        start = startdate + 'T' + starttime
        end = enddate + 'T' + endtime

    return start, end


def create_remote_task(client, feed_uri, task):

    # process meta
    meta = task['meta']

    start, end = process_datetime_from_timecode(task)

    event = gdata.calendar.data.CalendarEventEntry()

    starttime = task['starttime']
    endtime = task['endtime']

    event.title = atom.data.Title(task['description'])
    event.content = atom.data.Content(str(task['meta']))
    event.where.append(gdata.data.Where(value=task['location']))
    event.when.append(gdata.data.When(start=start, end=end))
    event = client.InsertEvent(event, feed_uri)
    return event_to_json(event)

def update_remote_task(client, feed_uri, eid, task):
    event_uri = feed_uri + '/' + eid[-26:]
    event = client.get_calendar_entry(event_uri, desired_class=gdata.calendar.data.CalendarEventEntry)

    meta = task['meta']

    start, end = process_datetime_from_timecode(task)
    
    event.title.text = task['description']
    event.content.text = str(task['meta'])
    event.where[0].value = task['location']

    event.when[0].start = start
    event.when[0].end = end
    event = client.Update(event)
    return event_to_json(event)

@app.route('/todomato/api/v1.0/update', methods = ['POST'])
def update_task():

    local_data = ast.literal_eval(request.get_data())

    current_time = string_to_time(local_data['auth']['current_time'])
    server_time = (datetime.datetime.now() + datetime.timedelta(hours=8))
    server_time = server_time.replace(microsecond = 0)
    time_offset = current_time - server_time
    print "\nSTART SYNCING \n====================\ntime offset: ", time_offset
    print "\nLOCAL DATA RECEIVED \n====================\nlocal data: \n", json.dumps(local_data, sort_keys=True, indent=4)
    
    local_tasklist = local_data['data']['tasklist']
    local_auth = local_data['auth']
    last_sync = local_data['auth']['last_sync']

    print '\nINITIALISATION\n====================\n'
    
    # create or get todomato
    remote_tasklist, client, feed_uri = init(local_auth)

    # update task
    print '\nUPDATING\n====================\n'
    tasklist = update(client, feed_uri, local_tasklist, remote_tasklist, last_sync, time_offset)
    # return task
    print '\nRESPONDING\n====================\n', json.dumps(tasklist, sort_keys=True, indent=4)
    return jsonify({ 'tasklist': tasklist }), 201


if __name__ == '__main__':
    app.run(debug = True)




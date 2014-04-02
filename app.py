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

app = Flask(__name__)


# helper functions

def normalize_time(datetime_string):
    datetime_string = (datetime.datetime.strptime(datetime_string, "%Y-%m-%dT%H:%M:%S.000Z") + datetime.timedelta(hours=8)).strftime("%Y-%m-%dT%H:%M:%S.000+08:00")
    return datetime_string

def string_to_time(datetime_string):
    return datetime.datetime.strptime(datetime_string, "%Y-%m-%dT%H:%M:%S.000+08:00")


def init(local_auth):
    username = local_auth['username']
    password = local_auth['password']
    client = gdata.calendar.client.CalendarClient(source='Todomato')

    client.ClientLogin(username, password, client.source)
    feed = client.GetAllCalendarsFeed()

    cid = None

    # create or get todomato calendar list
    for i, cal in zip(xrange(len(feed.entry)), feed.entry):
        if cal.title.text == "Todomato":
            cal_url = cal.id.text
    if cal_url == None:
        calendar = gdata.calendar.data.CalendarEntry()
        calendar.title = atom.data.Title(text="Todomato")
        calendar.timezone = gdata.calendar.data.TimeZoneProperty(value="Asia/Singapore")
        cal_url = client.InsertCalendar(new_calendar=calendar).id.text

    cid = cal_url.split("http://www.google.com/calendar/feeds/default/calendars/")[1]
    feed_uri = "http://www.google.com/calendar/feeds/%s/private/full" %(cid,)
    
    # get calendar events
    remote_tasklist = get_remote_tasks(client, feed_uri)

    return remote_tasklist, client, feed_uri

def update(client, feed_uri, local_tasklist, remote_tasklist, last_sync):

    if len(local_tasklist) == 0:
        local_tasklist = remote_tasklist
        return local_tasklist
    elif len(remote_tasklist) == 0:
        remote_tasklist = create_remote_tasks(client, feed_uri, local_tasklist)
        local_tasklist = remote_tasklist
        return local_tasklist
    else:
        last_sync_time = string_to_time(last_sync)
        for i in range(0, len(local_tasklist)):
            task = local_tasklist[i]
        # local create
            if 'eid' not in task:
                updated_task = create_remote_task(client, feed_uri, task)
                local_tasklist[i] = updated_task
            else:
                eid = task['eid']
                event = get_event_by_eid(remote_tasklist, eid)
                local_updated_time = string_to_time(task['edit'])
        # remote delete
                if event is None and local_updated_time < last_sync_time:
                    local_tasklist[i] = None
                elif event is not None:
                    remote_updated_time = string_to_time(event['edit'])
        # local or remote update
                    if local_updated_time > last_sync_time and remote_updated_time > last_sync_time:
                        if local_updated_time > remote_updated_time:
                            local_tasklist[i] = update_remote_task(client, feed_uri, eid, task)
                        elif local_updated_time < remote_updated_time:
                            local_tasklist[i] = event
        
        for event in remote_tasklist:
            eid = event['eid']
            remote_updated_time = string_to_time(event['edit'])
            local_task = get_event_by_eid(local_tasklist, eid)
            if local_task is None:
        # remote create
                if remote_updated_time > last_sync_time:
                    local_tasklist.append(event)
        # local detele      
                else:
                    event_uri = feed_uri + '/' + eid[-26:]
                    event = client.get_calendar_entry(event_uri, desired_class=gdata.calendar.data.CalendarEventEntry)
                    print event.GetEditLink()
                    client.Delete(event)

        local_tasklist = [t for t in local_tasklist if t is not None]

        return local_tasklist

def get_event_by_eid(tasklist, eid):
    for event in tasklist:
        if event['eid'] == eid:
            return event
    return None

def event_to_json(event):
    xmlstring = event.ToString()
    xml_dict = xmltodict.parse(xmlstring, process_namespaces=True)
    edit_time = normalize_time(xml_dict['http://www.w3.org/2005/Atom:entry']['http://www.w3.org/2005/Atom:updated'])
    created_time = normalize_time(xml_dict['http://www.w3.org/2005/Atom:entry']['http://www.w3.org/2005/Atom:published'])

    event_dict = {
            'eid':event.id.text,
            'description':event.title.text,
            'id':event.content.text,
            'starttime':event.when[0].start,
            'endtime':event.when[0].end,
            'location':event.where[0].value,
            'edit': edit_time,
            'created': created_time
        }

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

def create_remote_task(client, feed_uri, task):
    start_time = task['starttime']
    end_time = task['endtime']
    event = gdata.calendar.data.CalendarEventEntry()
    event.title = atom.data.Title(task['description'])
    event.content = atom.data.Content(task['id'])
    event.where.append(gdata.data.Where(value=task['location']))
    event.when.append(gdata.data.When(start=start_time, end=end_time))
    event = client.InsertEvent(event, feed_uri)
    return event_to_json(event)

def update_remote_task(client, feed_uri, eid, task):
    event_uri = feed_uri + '/' + eid[-26:]
    event = client.get_calendar_entry(event_uri, desired_class=gdata.calendar.data.CalendarEventEntry)
    start_time = task['starttime']
    end_time = task['endtime']
    event.title.text = task['description']
    event.content.text = task['id']
    event.where[0].value = task['location']
    event.when[0].start = task['starttime']
    event.when[0].end = task['endtime']
    event = client.Update(event)

    return event_to_json(event)

@app.route('/todomato/api/v1.0/update', methods = ['POST'])
def update_task():
    local_data = ast.literal_eval(request.get_data())
    local_tasklist = local_data['data']['tasklist']
    local_auth = local_data['auth']
    last_sync = local_data['auth']['last_sync']
    # create or get todomato
    remote_tasklist, client, feed_uri = init(local_auth)
    # update task
    tasklist = update(client, feed_uri, local_tasklist, remote_tasklist, last_sync)
    # return task
    return jsonify({ 'tasklist': tasklist }), 201


if __name__ == '__main__':
    app.run(debug = True)




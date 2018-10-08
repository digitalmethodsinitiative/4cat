# -*- coding: utf-8 -*-

import time as theendisnigh
import threading
import urllib.request, json
import pandas as pd
import re
import html2text
import io
import os
import ast
from bs4 import BeautifulSoup
from requests.exceptions import HTTPError
from PIL import Image
from nltk.text import Text
from nltk.tokenize import word_tokenize
from socket import timeout
from fourcat.colocation import *
from fourcat.wordfrequencies import *

li_no = []
li_opno = []
li_replies = []
li_comments = []
li_subjects = []
li_time = [] 
li_name = []
li_uniqueips = []
li_id = []
li_now = []
li_country = []
li_tim = []
li_allnos = []
li_ext = []
li_imgurl = []
li_imghash = []

columns = ['opno','no','replies','time','comment', 'now', 'country', 'subject', 'tim']
df = pd.DataFrame(columns=columns)

counter = 0
time = 0
firstpost = 0
lasttimeactive = 0

li_activethreads = []         #the pivotal list with the active threads
li_inactivethreads = []

di_metadata = {}
di_metadata['threadsmetadata'] = {}
di_threadmetadata = {}
di_threadsmetadata = {}
li_repliesarchived = []
li_uniqueipsarchived = []
li_timarchived = []
li_countriesarchived = []
li_allimages = []

def createNewSnapshot():
    #('createNewSnapshot() called')
    global li_activethreads
    global filetime
    global outputfolder
    global outputcsv
    filetime = ""
    outputfolder = ""
    outputcsv = ""
    filetime = str(theendisnigh.strftime("%d-%m-%Y-%H-%M-%S"))
    outputfolder = 'snapshots/snapshot-' + filetime
    outputcsv = outputfolder + '/' + filetime + '.csv'

    os.makedirs(outputfolder)

def startSnapshot(inputbool):
    global di_metadata
    global timeofquery
    timeofquery = str(theendisnigh.strftime("%Y-%m-%d %H:%M"))
    start = theendisnigh.time()

    print('Opening threads.json to register active threads')
    url_handle_all = urllib.request.urlopen("http://a.4cdn.org/pol/threads.json")   #json with all the ops, page 1-10
    data = url_handle_all.read().decode('utf-8', 'ignore')
    allpages = json.loads(data)

    li_activethreads = []
    newcount = 0
    try:
       with open(outputfolder + '/' + filetime + '-' + 'metadata.txt', 'r') as txt_storedthreads:   #also use the active threads from the round before
            di_threads = ast.literal_eval(txt_storedthreads.read())
            print(di_threads)
            for key, thread in di_threads['threadsmetadata'].items():
                if thread['reasonofclosure'] == 'stillopen':
                    li_activethreads.append(key)
            print(str(len(li_activethreads)) + ' old threads')
    except FileNotFoundError:
        print('No previous threads registered yet, first round of capturing')

    for pages in allpages:                         #loop through pages.   Put [x:] after allpages for testing.
        for threads in pages['threads']:           #loop through threads. Put [x:] after pages['threads'] for testing.
            if threads['no'] == 124205675 or threads['no'] == 143684145:  #filter out the sticky posts
                print('sticky thread')
            else:
                if threads['no'] not in li_activethreads:
                    li_activethreads.append(threads['no'])      #fill active threads list with all threads.json threads
                    newcount = newcount + 1
    print(str(newcount) + ' new threads')
    print('Starting with ' + str(len(li_activethreads)) + ' active threads')
    
    fetchPosts(li_activethreads, inputbool)
    
    if(len(li_activethreads) > 0): 
        print('fetched/updated posts, sleeping for an hour before running thread update')
        # sleepLog(3600)
    end = theendisnigh.time()
    print('Finished in ' + str((end - start)) + ' seconds')
    return outputcsv

def fetchPosts(activethreads, images):
    global li_activethreads
    global counter
    global opno
    try:                                                        #if metadata already exists, merge new and old metadata
        with open(outputfolder + '/' + filetime + '-' + 'metadata.txt', 'r') as txt_storedmetadata:
            di_metadata = ast.literal_eval(txt_storedmetadata.read())
    except FileNotFoundError:
        di_metadata = {}
        di_metadata['threadsmetadata'] = {}
        print('no metadata generated yet')

    li_imagestofetch = []
    threadnumbers = activethreads
    print('updating/fetching threads ' + str(threadnumbers))

    count_postshandled = 0
    count_postsskipped = 0
    li_threadslooped = threadnumbers

    for index, threadnumber in enumerate(reversed(li_threadslooped)):      #loop through all current threads (first two are ignored)
        threadactive = True

        while True:
            request = urllib.request.Request("http://a.4cdn.org/pol/thread/" + str(threadnumber) + ".json")

            reasonofclosure = 'stillopen'
            timeouttime = 8
            try:                                                            #error catching - deleted posts, timeouts etc
                response = urllib.request.urlopen(request, timeout=timeouttime)
            except timeout:
                print('Connection timed out, sleeping for 1 minutes')
                sleepLog(60)
                pass
            except urllib.error.HTTPError as httperror:      #some threads get deleted and return a 404
                print('HTTP error when requesting thread json')
                print('Reason:', httperror.code)
                print('HTTP error ' + str(httperror.code) + ' for thread ' + str(threadnumber))
                print('Adding thread ' + str(threadnumber) + ' to inactive threads')
                
                reasonofclosure = 'httperror'
                if threadnumber in di_metadata['threadsmetadata']:              # if the thread was already registered and now closed, only update 'reasonofclosure'
                    di_metadata['threadsmetadata'][threadnumber]['reasonofclosure'] = 'httperror'
                else:
                    di_metadata['threadsmetadata'][threadnumber] = {}
                    di_metadata['threadsmetadata'][threadnumber]['reasonofclosure'] = 'httperror'

                print(di_metadata['threadsmetadata'][threadnumber])
                #sleepLog(2)
                break
            except ConnectionError:
                print('Connection refused by the remote host...\nSleeping for 60 seconds.')
                sleepLog(60)
                pass
            except ConnectionAbortedError:
                print('Connection refused by the remote host...\nSleeping for 60 seconds.')
                sleepLog(60)
                pass
            except ConnectionResetError:
                print('Connection refused by the remote host...\nSleeping for 60 seconds.')
                sleepLog(60)
                pass
            else:
                url_handle_thread = response
                threadtimestamp = int(theendisnigh.time())
                lastactivity = threadtimestamp
                threaddata = url_handle_thread.read().decode('utf-8')
                threadjson = json.loads(threaddata)

                del li_no[:]                          #remove all the previous data - the csv is written per thread
                del li_opno[:]
                del li_replies[:]
                del li_uniqueips[:]
                del li_comments[:]
                del li_time[:] 
                del li_now[:]
                del li_country[:]
                del li_subjects[:]
                del li_name[:]
                del li_id[:]
                del li_tim[:]
                del li_imgurl[:]
                del li_ext[:]
                del li_imghash[:]

                postoffset = 0            #if the thread is already registered, determine an offset for posts
                startpost = threadjson['posts'][0]
                nokey = startpost['no']
                closedstatechanged = False

                if threadnumber in di_metadata['threadsmetadata']:
                    postoffset = di_metadata['threadsmetadata'][threadnumber]['lasttimeactive']
                    #print(postoffset)
                    firstpost = di_metadata['threadsmetadata'][threadnumber]['firstpost']
                archivedkey = 'archived'
                closedkey = 'closed'
                if archivedkey in startpost:
                    if startpost['archived'] == 1:  #check whether post was closed or archived
                        archivedonkey = 'archived_on'              #check if entry has a subject
                        reasonofclosure = 'archived'
                        if archivedonkey in startpost:
                            lastactivity = startpost['archived_on']
                            closedstatechanged = True
                        print('Thread archived\nAdded thread ' + str(threadnumber) + ' to inactive threads')

                for post in threadjson['posts']:        #loop through posts in thread
                    if post['time'] > postoffset:      #only fetch post when it is posted later than last known post in thread
                        comkey = 'com'
                        subkey = 'sub'
                        timkey = 'tim'
                        countrykey = 'country_name'
                        idkey = 'id'
                        namekey = 'name'
                        uniqueipkey = 'unique_ips'

                        opnumber = ''
                        if post['resto'] == 0:
                            opno = post['no']
                            replies = post['replies']
                            opnumber = opno
                            firstpost = post['time']      #if it's the first post, store the value for metadata
                        else:
                            replies = ''
                            opnumber = opno
                        no = post['no']

                        if uniqueipkey in post:
                            if uniqueipkey is not '':
                                uniqueips = post['unique_ips']
                                li_uniqueipsarchived.append(uniqueips)
                        else:
                            uniqueips = ''
                        
                        if comkey in post:        #check if comment exists (not all posts have coms)
                            comment = post['com']
                            comment = comment.replace('<br>', ' ')
                            comment = BeautifulSoup(comment, 'html.parser')
                            comment = comment.get_text()
                            comment = comment.encode('utf-8')
                            comment = comment.decode('utf-8')
                        else:
                            comment = ''

                        if subkey in post:        #check if entry has a subject
                            subject = post['sub']
                            subject = BeautifulSoup(subject, 'html.parser')
                            subject = subject.get_text()
                            subject = subject.encode('utf-8')
                            subject = subject.decode('utf-8')
                        else:
                            subject = ''

                        if idkey in post:            #check if entry has an id
                            idstring = post['id']
                        else:
                            idstring = ''

                        if namekey in post:    #check if entry has a subject
                            namestring = post['name']
                            namestring = BeautifulSoup(namestring, 'html.parser')
                            namestring = namestring.get_text()
                            namestring = namestring.encode('utf-8')
                            namestring = namestring.decode('utf-8')
                        else:
                            namestring = '' 

                        time = post['time']
                        lasttimeactive = time
                        now = post['now']

                        if countrykey in post:      #check if entry has countrykey
                            country = post['country_name']
                            country = BeautifulSoup(country, 'html.parser')
                            country = country.get_text()
                            country = country.encode('utf-8')
                            country = country.decode('utf-8')
                        else:
                            country = ''

                        if timkey in post:
                            ext = post['ext']         #download the images
                            tim = post['tim']
                            imghash = post['md5']
                            imageurl = 'img/' + str(opno)+'-'+str(tim)+str(ext)
                            li_imagestofetch.append(str(opno)+'-'+str(tim)+str(ext))
                        else:
                            tim = ''
                            ext = ''
                            imageurl = ''
                            imghash = ''

                        li_no.append(no)                #put info in lists
                        li_opno.append(opnumber)
                        li_replies.append(replies)
                        li_repliesarchived.append(replies)
                        li_comments.append(comment)
                        li_subjects.append(subject)
                        li_id.append(idstring)
                        li_uniqueips.append(uniqueips)
                        li_name.append(namestring)
                        li_time.append(time)
                        li_now.append(now)
                        li_country.append(country)
                        li_countriesarchived.append(country)
                        li_tim.append(tim)
                        li_ext.append(ext)
                        li_imgurl.append(imageurl)
                        li_timarchived.append(tim)
                        li_imghash.append(imghash)

                        count_postshandled = count_postshandled + 1

                    else:
                        #post already registered
                        count_postsskipped = count_postsskipped + 1
        
                #when one thread is finished:
                if count_postshandled > 0 or closedstatechanged:      #and if there were actually new posts to process
                    if threadnumber in di_metadata['threadsmetadata']:
                        di_threadmetadata = di_metadata['threadsmetadata'][threadnumber]
                    else:
                        di_threadmetadata = {}
                        di_threadmetadata['pagepositions'] = {}
                    
                    di_threadmetadata['firstpost'] = startpost['time']
                    if reasonofclosure == 'archived':
                        di_threadmetadata['archived_on'] = startpost['archived_on']
                    if 'unique_ips' in startpost:
                        di_threadmetadata['uniqueips'] = startpost['unique_ips']
                    
                    di_threadmetadata['lasttimeactive'] = lasttimeactive        #time of last post
                    di_threadmetadata['secondsactive'] = (lastactivity - firstpost)
                    di_threadmetadata['reasonofclosure'] = reasonofclosure
                    di_threadmetadata['posts'] = startpost['replies'] + 1

                    di_metadata['threadsmetadata'][threadnumber] = di_threadmetadata   #append threads dict to metadata dict
                    #print(di_threadmetadata)
                    writeCSV()
                
                # determining what postition the post was on at time of query
                if reasonofclosure == 'stillopen':
                    di_metadata['threadsmetadata'][threadnumber]['pagepositions'][timeofquery] = index + 1
                else:
                    di_metadata['threadsmetadata'][threadnumber]['pagepositions'][timeofquery] = -1
                    
                # theendisnigh.sleep(1)
                break

        print('Finished thread ' + str(threadnumber)+ '\n' + str(index + 1) + ' / ' + str(len(li_threadslooped)) + ' threads complete')
        ##print('Old posts (skipped): ' + str(count_postsskipped))
        ##print('New posts (registered): ' + str(count_postshandled))
        count_postshandled = 0
        count_postsskipped = 0
        closedstatechanged = False
        counter = counter + 1
        # theendisnigh.sleep(7)      #to not freeze my computer and to save 4chan's servers

    #when all threads are finished:
    writeMetaResults(di_metadata)
    li_activethreads = []
    li_inactivethreads = []
    for key, value in di_metadata['threadsmetadata'].items():
        if value['reasonofclosure'] == 'stillopen':
            li_activethreads.append(key)
        if value['reasonofclosure'] == 'archived' or value['reasonofclosure'] == 'httperror':
            li_inactivethreads.append(key)
    print(str(len(li_inactivethreads)) + ' threads closed: ' + str(li_inactivethreads))
    print(str(len(li_activethreads)) + ' threads still active: ' + str(li_activethreads))
    count_activethreads = len(li_activethreads)
    
    if images == True:
        li_imagestofetch = [image for image in li_imagestofetch if image not in li_allimages] #comment/uncomment to fetch images
        getImages(li_imagestofetch)
        li_allimages.append(li_imagestofetch)
        del li_imagestofetch[:]

def getImages(imagelist):
    li_images = imagelist
    size = 800, 800

    print('Fetching images...')

    os.makedirs(outputfolder + '/img/')

    for index, postimage in enumerate(li_images):
        imagename = postimage[10:]
        # print('Getting and resizing image ' + imagename)
        extlist = postimage.split('.')
        extfile = extlist[1]
        ext = '.' + extlist[1]
        while True:
            request = urllib.request.Request('http://i.4cdn.org/pol/' + str(imagename))
            try:                                    #check if the thread is still active on the site
                response = urllib.request.urlopen(request)

            except urllib.error.HTTPError as httperror:        #some threads get deleted and return a 404
                print('HTTP error when requesting thread')
                print('Reason:', httperror.code)
                if httperror.code != 404:
                    sleepLog(120)
                pass
            except ConnectionError:
                print('Connection refused by the remote host...\nSleeping for 120 seconds.')
                sleepLog(120)
                pass
            except ConnectionAbortedError:
                print('Connection refused by the remote host...\nSleeping for 120 seconds.')
                sleepLog(120)
                pass
            except ConnectionResetError:
                print('Connection refused by the remote host...\nSleeping for 120 seconds.')
                sleepLog(120)
                pass
            else:
                if ext == '.webm':            #check whether the file is an image
                    print('webm file, discarding')
                    # urllib.request.urlretrieve(imageurl, outputfolder+'/img/'+ str(postimage))
                else:
                    #resizing images
                    imagefile = io.BytesIO(response.read())
                    image = Image.open(imagefile)
                    imagesize = image.size
                    if imagesize[0] > 800 or imagesize[1] > 800:
                        # print('Resizing...')
                        image.thumbnail(size)
                    image.save(outputfolder + '/img/' + postimage)
                print('Image ' + str(index  + 1) + '/' + str(len(li_images)) + ' downloaded')
            
            # theendisnigh.sleep(1)
            # if (index + 1) % 100 == 0:                          #so 4chan doesn't kick me out
                # print('sleeping for 10 seconds')
                # theendisnigh.sleep(10)
            break

def writeMetaResults(di_input):
    input_metadata = di_input
    print(input_metadata)
    
    # di_commentsdata = {}
    # cumulatedreplies = 0                                    #calculate the total and average amount of comments
    # li_replyamount = []
    # for reply in li_repliesarchived:
    #     if reply is not '':
    #         cumulatedreplies = cumulatedreplies + reply + 1 #add 1 to include OP number
    #         li_replyamount.append(reply + 1)
    # print('cumulatedreplies: ' + str(cumulatedreplies) + '\nlen(li_replyamount): ' + str(len(li_replyamount)))
    # averagereplies = cumulatedreplies / (len(li_replyamount) + 1)
    # di_commentsdata['posts_amount'] = cumulatedreplies
    # di_commentsdata['posts_average'] = averagereplies

    # cumulatedips = 0
    # amountofentries = 0
    # for ips in li_uniqueipsarchived:
    #     cumulatedips = cumulatedips + ips
    # if amountofentries > 0:          #sometimes the averageips key exists in no posts
    #     averageips = cumulatedips / len(li_uniqueipsarchived)
    #     di_commentsdata['averageips'] = averageips

    # imagecounter = 0                                         #calculate the total amount of images/textposts
    # textcounter = 0
    # for image in li_timarchived:
    #     if image is not '':
    #         imagecounter = imagecounter + 1

    # di_commentsdata['images_amount'] = imagecounter
    # di_commentsdata['text_posts'] = imagecounter / cumulatedreplies
    # di_metadata['commentsdata'] = di_commentsdata

    # for flag in li_countriesarchived:       #average country contributions codes
    #    if flag is not '':
    #       if flag not in di_countryflags:
    #          di_countryflags[flag] = 1
    #       else:
    #          di_countryflags[flag] += 1
    # di_metadata['countrydata'] = di_countryflags

    write_handle = open(outputfolder + '/' + filetime + '-' + 'metadata.txt',"w")
    write_handle.write(str(input_metadata)) 
    write_handle.close()
    print('Meta results: ' + str(input_metadata))
    di_closedthreadmetadata = {}

def writeCSV():
    #print('Starting to write to csv')
    columns = ['threadnumber','no','now','time','comment', 'subject','replies','uniqueips','name','id','country','imagefile','ext','imageurl','imagehash']
    df = pd.DataFrame(columns=columns)
    df['threadnumber'] = li_opno                        #add the lists to the pandas DataFrame
    df['no'] = li_no
    df['now'] = li_now
    df['time'] = li_time
    df['comment'] = li_comments
    df['subject'] = li_subjects
    df['replies'] = li_replies
    df['uniqueips'] = li_uniqueips
    df['name'] = li_name
    df['id'] = li_id
    df['country'] = li_country
    df['imagefile'] = li_tim
    df['ext'] = li_ext
    df['imageurl'] = li_imgurl
    df['imagehash'] = li_imghash

    with open(outputcsv, 'a', encoding='utf-8') as f:
        if counter == 0:
            df.to_csv(f, index=False, encoding='utf-8')  #write headers at the first line
        else:
            df.to_csv(f, header=None, index=False, encoding='utf-8')
    #print('Finished writing thread to csv')

def resetVariables():                               #clear all variables for new scheduled run
    del li_no[:]
    del li_opno[:]
    del li_replies[:]
    del li_comments[:]
    del li_subjects[:]
    del li_time[:] 
    del li_name[:]
    del li_uniqueips[:]
    del li_id[:]
    del li_now[:]
    del li_country[:]
    del li_tim[:]
    del li_allnos[:]
    del li_ext[:]
    del li_imgurl[:]
    del li_imghash[:]

    df.iloc[0:0]

    counter = 0
    time = 0
    firstpost = 0
    lasttimeactive = 0

    di_metadata.clear()
    di_threadmetadata.clear()
    di_threadsmetadata.clear()
    del li_repliesarchived[:]
    del li_uniqueipsarchived[:]
    del li_timarchived[:]
    del li_countriesarchived[:]
    del li_allimages[:]
    di_metadata['threadsmetadata'] = {}

def sleepLog(seconds):
    secondstowait = seconds
    for seconds in range(secondstowait):
        if seconds % 10 == 0:
            print('Sleeping for ' + str((secondstowait - seconds)) + ' seconds')
            theendisnigh.sleep(10)
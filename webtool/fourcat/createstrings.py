def createStrings(df, outputform, platform):
	inputsheet = df
	output = outputform
	platformselected = platform
	if platformselected == 'chans':
		li_posts = inputsheet['comment'].tolist()
		#li_threadnumberlist = inputsheet.threadnumber.tolist()
	elif platformselected == 'reddit':
		li_posts = inputsheet['title'].tolist()
		#li_threadnumberlist = inputsheet.threadnumber.tolist()
	elif platformselected == 'fb':
		li_posts = inputsheet['name'].tolist()
		#li_threadnumberlist = inputsheet.threadnumber.tolist()

	li_posts = li_posts[1:]
	#li_threadnumberlist = li_threadnumberlist[1:]

	if output == 'fullcorpus':
		longstring = ''
		for comment in li_posts:
			if type(comment) is not float:
				newcomment = comment.encode('utf-8', 'ignore').decode('utf-8','ignore')
				longstring = longstring + newcomment + ' '
		return longstring


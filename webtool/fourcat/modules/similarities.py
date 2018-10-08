from __future__ import print_function
import sqlite3
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt, mpld3
import time
import re
import os
import nltk
import pickle
import operator
import json
from fourcat.createHistogram import createCosineDistHisto
#import glove_python
from matplotlib.font_manager import FontProperties
from nltk.stem.snowball import SnowballStemmer
from nltk.corpus import stopwords
from scipy.interpolate import spline
from datetime import datetime, timedelta
from collections import OrderedDict
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.cluster import KMeans
from sklearn.externals import joblib
from sklearn.manifold import MDS
from sklearn.manifold import TSNE
from sklearn.decomposition import PCA
from gensim.models import Word2Vec, KeyedVectors
from gensim.models import fasttext
from gensim.scripts.word2vec2tensor import word2vec2tensor
from matplotlib import pyplot
from adjustText import adjust_text

#month variables, so I don't have to mess with datetime
li_months = ['10-2015','11-2015','12-2015','01-2016','02-2016','03-2016','04-2016','05-2016','06-2016','07-2016','08-2016','09-2016','10-2016','11-2016','12-2016','01-2017','02-2017','03-2017','04-2017','05-2017','06-2017','07-2017','08-2017','09-2017','10-2017','11-2017','12-2017','01-2018','02-2018','03-2018']

li_filenames_months = ['01-16.csv', '01-17.csv', '01-18.csv', '02-16.csv', '02-17.csv', '02-18.csv', '03-16.csv', '03-17.csv', '04-16.csv', '04-17.csv', '05-16.csv', '05-17.csv', '06-15.csv', '06-16.csv', '06-17.csv', '07-15.csv', '07-16.csv', '07-17.csv', '08-15.csv', '08-16.csv', '08-17.csv', '09-15.csv', '09-16.csv', '09-17.csv', '10-15.csv', '10-16.csv', '10-17.csv', '11-15.csv', '11-16.csv', '11-17.csv', '12-15.csv', '12-16.csv', '12-17.csv']

li_labels_months = ['06-15', '07-15', '08-15', '09-15', '10-15', '11-15', '12-15', '01-16', '02-16', '03-16', '04-16', '05-16', '06-16', '07-16', '08-16', '09-16', '10-16', '11-16', '12-16', '01-17', '02-17', '03-17', '04-17', '05-17', '06-17', '07-17', '08-17', '09-17', '10-17', '11-17', '12-17','01-18', '02-18']

li_filenames_weeks = ['2015-26', '2015-27', '2015-28', '2015-29', '2015-30', '2015-31', '2015-32', '2015-33', '2015-34', '2015-35', '2015-36', '2015-37', '2015-38', '2015-39', '2015-40', '2015-41', '2015-42', '2015-43', '2015-44', '2015-45', '2015-46', '2015-47', '2015-48', '2015-49', '2015-50', '2015-51', '2015-52', '2016-00', '2016-01', '2016-02', '2016-03', '2016-04', '2016-05', '2016-06', '2016-07', '2016-08', '2016-09', '2016-10', '2016-11', '2016-12', '2016-13', '2016-14', '2016-15', '2016-16', '2016-17', '2016-18', '2016-19', '2016-20', '2016-21', '2016-22', '2016-23', '2016-24', '2016-25', '2016-26', '2016-27', '2016-28', '2016-29', '2016-30', '2016-31', '2016-32', '2016-33', '2016-34', '2016-35', '2016-36', '2016-37', '2016-38', '2016-39', '2016-40', '2016-41', '2016-42', '2016-43', '2016-44', '2016-45', '2016-46', '2016-47', '2016-48', '2016-49', '2016-50', '2016-51', '2016-52', '2017-00', '2017-01', '2017-02', '2017-03', '2017-04', '2017-05', '2017-06', '2017-07', '2017-08', '2017-09', '2017-10', '2017-11', '2017-12', '2017-13', '2017-14', '2017-15', '2017-16', '2017-17', '2017-18', '2017-19', '2017-20', '2017-21', '2017-22', '2017-23', '2017-24', '2017-25', '2017-26', '2017-27', '2017-28', '2017-29', '2017-30', '2017-31', '2017-32', '2017-33', '2017-34', '2017-35', '2017-36', '2017-37', '2017-38', '2017-39', '2017-40', '2017-41', '2017-42', '2017-43', '2017-44', '2017-45', '2017-46', '2017-47', '2017-48', '2017-49', '2017-50', '2017-51', '2017-52', '2018-01', '2018-02', '2018-03', '2018-04', '2018-05', '2018-06', '2018-07', '2018-08', '2018-09', '2018-10', '2018-11']

def getTokens(li_strings='', stemming=False):
	# if stemming:
	# 	global di_stems
	# 	di_stems = pickle.load(open('di_stems.p', 'rb'))

	print('imported')
	#do some cleanup: only alphabetic characters, no stopwords
	# create separate stemmed tokens, to which the full strings will be compared to:
	li_comments_stemmed = []
	len_comments = len(li_strings)
	print(len(li_strings))
	print('Creating list of tokens per monthly document')
	for index, comment in enumerate(li_strings):
		#create list of list for comments and tokens
		if isinstance(comment, str):
			li_comment_stemmed = []
			li_comment_stemmed = tokeniserAndStemmer(comment, stemming=stemming)
			li_comments_stemmed.append(li_comment_stemmed)
		if index % 1000 == 0:
			print('Stemming/tokenising finished for string ' + str(index) + '/' + str(len_comments))
	print(len(li_comments_stemmed))

	# if stemming:
	# 	pickle.dump(di_stems, open('di_stems.p', 'wb'))
	# 	df_stems = pd.DataFrame.from_dict(di_stems, orient='index')
	# 	df_stems.to_csv('di_stems_dataframe.csv', encoding='utf-8')

	return li_comments_stemmed

def tokeniserAndStemmer(string, stemming=False):
	#first, remove urls
	if 'http' in string:
		string = re.sub(r'https?:\/\/.*[\r\n]*', ' ', string)
	if 'www.' in string:
		string = re.sub(r'www.*[\r\n]*', ' ', string)

	#use nltk's tokeniser to get a list of words
	tokens = [word for sent in nltk.sent_tokenize(string) for word in nltk.word_tokenize(sent)]
	stemmer = SnowballStemmer("english")
	#list with tokens further processed
	li_filtered_tokens = []
	# filter out any tokens not containing letters (e.g., numeric tokens, raw punctuation)
	for token in tokens:
		#only alphabetic characters
		if re.search('[a-zA-Z]', token):
			#only tokens with three or more characters
			if len(token) >= 3:
				#no stopwords
				if token not in stopwords.words('english'):
					token = token.lower()
					#shorten word if it's longer than 20 characters (e.g. 'reeeeeeeeeeeeeeeeeeeeeeeee')
					if len(token) >= 20:
						token = token[:20]
					#stem if indicated it should be stemmed
					if stemming:
						token_stemmed = stemmer.stem(token)
						li_filtered_tokens.append(token_stemmed)

						#update lookup dict with token and stemmed token
						#lookup dict is dict of stemmed words as keys and lists as full tokens
						# if token_stemmed in di_stems:
						# 	if token not in di_stems[token_stemmed]:
						# 		di_stems[token_stemmed].append(token)
						# else:
						# 	di_stems[token_stemmed] = []
						# 	di_stems[token_stemmed].append(token)
					else:
						li_filtered_tokens.append(token)
	return li_filtered_tokens

def getDocSimilarity(li_strings='', dateformat = 'weeks', maxdf = '', dates='', querystring='', load=False, kmeansgraph=False, createcosinematrix=True, storetop100=True, writetfidfcsv=True, load_kmeans=False, mds=True, num_clusters=3, num_kmeans=3):
	print(len(li_strings))
	if maxdf == '':
		maxdf = (len(li_strings) - 1)
		print(maxdf)
	if load == False:
		#max_df used to filter out words like 'like' and 'trump'. Check https://stackoverflow.com/questions/46118910/scikit-learn-vectorizer-max-features?utm_medium=organic&utm_source=google_rich_qa&utm_campaign=google_rich_qa
		tfidf_vectorizer = TfidfVectorizer(min_df=1, max_df=maxdf, stop_words='english', analyzer='word', token_pattern=u'(?u)[-//a-zA-Z0-9]{3,}')
		print('Creating tf-idf vector of input documents')
		#prepare vectorizer
		#create tf_idf vectors of month-separated comments
		tfidf_matrix = tfidf_vectorizer.fit_transform(li_strings)
		pickle.dump(tfidf_vectorizer, open('tfidf/trump_tfidf_vectorizer_' + dateformat + '.p', 'wb'))
		pickle.dump(tfidf_matrix, open('tfidf/trump_tfidf_matrix_' + dateformat + '.p', 'wb'))
		pickle.dump(tfidf_matrix, open('tfidf/trump_li_strings_' + dateformat + '.p', 'wb'))
	else:
		tfidf_vectorizer = pickle.load(open('tfidf/trump_tfidf_vectorizer_' + dateformat + '.p', 'rb'))
		tfidf_matrix = pickle.load(open('tfidf/trump_tfidf_matrix_' + dateformat + '.p', 'rb'))
		li_strings = pickle.load(open('tfidf/trump_li_strings_' + dateformat + '.p', 'rb'))

	print(tfidf_matrix[:10])

	# feature_array = np.array(tfidf_vectorizer.get_feature_names())
	# tfidf_sorting = np.argsort(tfidf_matrix.toarray()).flatten()[::-1]
	# #print and store top n highest scoring tf-idf scores
	# n = 200
	# top_n = feature_array[tfidf_sorting][:n]
	# print(top_n)

	weights = np.asarray(tfidf_matrix.mean(axis=0)).ravel().tolist()
	df_weights = pd.DataFrame({'term': tfidf_vectorizer.get_feature_names(), 'weight': weights})
	df_weights = df_weights.sort_values(by='weight', ascending=False).head(100)
	df_weights.to_csv('tfidf/tfidf_top100_' + dateformat + '.csv', encoding='utf-8')
	print(df_weights.head())

	df_matrix = pd.DataFrame(tfidf_matrix.toarray(), columns=tfidf_vectorizer.get_feature_names())
	
	#turn the dataframe 90 degrees
	df_matrix = df_matrix.transpose()
	print('Amount of words: ' + str(len(df_matrix)))
	
	if writetfidfcsv:
		print('Writing tf-idf vector to csv')
		# #do some editing of the dataframe
		if dateformat == 'months':
			df_matrix.columns = li_filenames_months
			cols = df_matrix.columns.tolist()
			cols = li_filenames_months
		elif dateformat == 'weeks':
			df_matrix.columns = li_filenames_weeks
			cols = df_matrix.columns.tolist()
			cols = li_filenames_weeks
		df_matrix = df_matrix[cols]
		df_matrix.to_csv('tfidf/trump_matrix_' + dateformat + '.csv', encoding='utf-8')
	
	if createcosinematrix:
		# #make a cosine similarity matrix between documents
		print('Creating cosine similarity matrix')
		cosine_sim = (tfidf_matrix * tfidf_matrix.T).toarray()
		print(cosine_sim)
		df_cosine_matrix = pd.DataFrame(cosine_sim)
		df_cosine_matrix.to_csv('tfidf/trump_cosine_matrix_' + dateformat + '.csv', encoding='utf-8')

	if storetop100:
		# store top 100 terms per doc in a csv ('tfidf_top100_weeks.csv')
		for index, doc in enumerate(df_matrix):
			print(doc)
			df_tim = (df_matrix.sort_values(by=[doc], ascending=False))[:100]
			df_timesep = pd.DataFrame()
			df_timesep[doc] = returnNonStemmed(df_tim.index.values[:100])
			df_timesep['tfidf_score'] = df_tim[doc].values[:100]
			print(df_timesep[:10])
			#if index == 0:
				# with open('tfidf/tfidf_top100_' + dateformat + '.csv', 'w') as f:
				# 	df_timesep.to_csv(f, encoding='utf-8')
			#else:
				#df_full = with open('tfidf/tfidf_top100_' + dateformat + '.csv', 'a') as f:
				#df_full = pd.read_csv('tfidf/tfidf_top100_' + dateformat + '.csv', encoding='utf-8')
			if index == 0:
				df_full = df_timesep
			else:
				df_full = pd.concat([df_full, df_timesep], axis=1)
		# df_full.to_csv('tfidf/tfidf_top100_' + dateformat + '.csv', encoding='utf-8')
		# df_noweight = df_full.iloc[0:,::2]
		# df_noweight.to_csv('tfidf/tfidf_top100_noweight_' + dateformat + '.csv', encoding='utf-8', index=False)

		# df_rankflow = pd.read_csv('tfidf/tfidf_top100_' + dateformat + '.csv', encoding='utf-8')
		# df_rankflow = df_rankflow.drop(df_rankflow.columns[0], axis=1)
		# print(df_rankflow)
		# for col in df_rankflow.columns:
		# 	print(col)
		# 	if 'tfidf' in col:
		# 		vals = [int(tfidf * 100) for tfidf in df_rankflow[col]]
		# 		df_rankflow[col] = vals

		# df_rankflow.to_csv('tfidf/tfidf_top100_rankflow_' + dateformat + '.csv', encoding='utf-8', index=False)

	#create a scatter plot with k-means topics
	if kmeansgraph:
		print('Calculating document similarities')
		terms = tfidf_vectorizer.get_feature_names()
		#print(terms)
		dist = 1 - cosine_similarity(tfidf_matrix)
		print(dist)

		num_clusters = num_kmeans

		if load_kmeans:
			# loading existing clusters for debugging/testing
			k_means = pickle.load(open('clusters/doc_cluster_' + querystring + '_' + str(num_clusters) + 'clusters_' + dateformat + '.p', 'rb'))
			clusters = k_means.labels_.tolist()
		else:
			#create new K-means clusters
			k_means = KMeans(n_clusters=num_kmeans)
			k_means.fit(tfidf_matrix)
			clusters = k_means.labels_.tolist()
			print(clusters)
			pickle.dump(k_means, open('clusters/doc_cluster_' + querystring + '_' + str(num_kmeans) + 'clusters_' + dateformat + '.p', 'wb'))

			# clusters = k_means.labels_.tolist()
			di_clusters = {'dates': dates, 'text': li_strings, 'cluster': clusters}
			df_kclusters = pd.DataFrame(di_clusters, index=[clusters], columns = ['dates', 'cluster'])
			df_kclusters.to_csv('clusters/cluster_'+ querystring + '_' + str(num_kmeans) + '_' + dateformat + '.csv')

		# Predicting the clusters
		labels = k_means.predict(tfidf_matrix)
		# get centres for clusters for labels
		centroids = k_means.cluster_centers_.argsort()[:, ::-1]
		print(centroids)
		# sort clusters by proximity to central points (centroids)
		order_centroids = k_means.cluster_centers_.argsort()[:, ::-1] 

		di_cluster_colors = {0: '#d283a7', 1:'#52b6dd', 2: '#eadb8f', 3: '#69b57e', 4: '#d7815c', 5: '#4facb4', 6: '#96382c', 7: '#8895d5', 8: '#b49c5b', 9: '#d8d8d8', 10: '#d65786', 11: '#909687', 12: '#8bad54'}
		cmap = ['#d283a7', '#52b6dd','#eadb8f','#69b57e','#d7815c','#4facb4','#96382c','#8895d5','#b49c5b','#d8d8d8', '#d65786', '#909687', '#8bad54']
		# non-dimenstionality reduction, either with k means scatter or MDS
		
		di_cluster_names = {}
		for i in range(num_kmeans):
			clusterstring = ''
			print("Cluster %d:" % i),
			for index, ind in enumerate(order_centroids[i, :5]):
				print(ind)
				print(' %s' % terms[ind])
				if index == 0:
					clusterstring += '' + str(returnNonStemmed(terms[ind]))
				else:
					clusterstring += ', ' + str(returnNonStemmed(terms[ind]))
			di_cluster_names[i] = clusterstring

		if mds == False:
			print(dist)
			#print(terms)
			dist = dist[2:]
			dates = dates[2:]
			kmeans = KMeans(n_clusters=num_clusters)
			kmeans.fit(dist)
			y_kmeans = kmeans.predict(dist)
			fig, ax = plt.subplots(figsize=(10, 8))
			#plt.scatter(dist[:, 0], dist[:, 1], c=y_kmeans, s=50, cmap=cmap)
			for i in range(len(dist)):
				ax.plot(dist[:, 0][i], dist[:, 1][i], marker='o', linestyle='', markersize=10, zorder=1, label=di_cluster_names[clusters[i]], color=di_cluster_colors[clusters[i]], mec='none')
				ax.annotate(dates[i], (dist[:, 0][i], dist[:, 1][i]), size=7)
			
			centers = kmeans.cluster_centers_
			plt.plot(centers[:, 0], centers[:, 1], marker='x', linestyle='', color='#d12d04', zorder=100, markeredgewidth=4, markersize=10, alpha=1);

			fontP = FontProperties()
			fontP.set_size('small')
			# Shrink current axis's height by 10% on the bottom
			# box = ax.get_position()
			# ax.set_position([box.x0, box.y0 + box.height * 0.1, box.width, box.height * 0.9])
			# Put a legend below ax
			legend = ax.legend(loc='upper center', bbox_to_anchor=(0.5, -0.05), borderaxespad=0., fancybox=True, shadow=True, ncol=1, prop=fontP)
			#ax.plot(centroids[:, 0], centroids[:, 1], marker='x', color='r');
			plt.setp(legend.get_title(), fontsize=10)
			#remove duplicate legend entries - a bit hacky but time is of the essence
			handles, labels = plt.gca().get_legend_handles_labels()
			by_label = OrderedDict(zip(labels, handles))
			plt.legend(by_label.values(), by_label.keys())
			plt.title('K-means clusters of weekly time-separated documents of all Trump-dense threads')
			
			plt.show()

		else:
			# convert two components as we're plotting points in a two-dimensional plane
			# "precomputed" because we provide a distance matrix
			MDS()
			mds = MDS(n_components=2, dissimilarity="precomputed", random_state=1)
			pos = mds.fit_transform(dist)  # shape (n_components, n_samples)

			xs, ys = pos[:, 0], pos[:, 1]
			print()
			print()

			#create df that has the result of the MDS plus the cluster numbers and titles
			df_plot = pd.DataFrame(dict(x=xs, y=ys, label=clusters, title=dates)) 
			
			#group by cluster
			groups = df_plot.groupby('label')

			fig, ax = plt.subplots(figsize=(10, 8)) # set size
			ax.margins(0.05) # Optional, just adds 5% padding to the autoscaling
			
			#plt.plot(centr[:, 0], centr[:, 1], marker='x', linestyle='', color='#d12d04', zorder=100, markeredgewidth=4, markersize=10, alpha=1);

			#iterate through groups to layer the plot
			for name, group in groups:
				print(name, group)
				ax.plot(group.x, group.y, marker='o', linestyle='', ms=12, 
			            label=di_cluster_names[name], color=di_cluster_colors[name], 
			            mec='none')
				ax.set_aspect('auto')
				ax.tick_params(\
			        axis= 'x',         # changes apply to the x-axis
			        which='both',      # both major and minor ticks are affected
			        bottom='off',      # ticks along the bottom edge are off
			        top='off',         # ticks along the top edge are off
			        labelbottom='off')
				ax.tick_params(\
			        axis= 'y',         # changes apply to the y-axis
			        which='both',      # both major and minor ticks are affected
			        left='off',        # ticks along the bottom edge are off
			        top='off',         # ticks along the top edge are off
			        labelleft='off')

			#add label in x,y position with the label as the date
			for i in range(len(df_plot)):
				ax.text(df_plot.ix[i]['x'], df_plot.ix[i]['y'], df_plot.ix[i]['title'], size=8)  
			
			fontP = FontProperties()
			fontP.set_size('small')
			# Shrink current axis's height by 10% on the bottom
			# box = ax.get_position()
			# ax.set_position([box.x0, box.y0 + box.height * 0.1, box.width, box.height * 0.9])
			# Shrink current axis by 10%
			box = ax.get_position()
			ax.set_position([box.x0, box.y0, box.width * 0.87, box.height])

			# Put a legend below ax
			legend = ax.legend(loc='center left', bbox_to_anchor=(1, 0.5), borderaxespad=0., ncol=1, prop=fontP)
			#ax.plot(centroids[:, 0], centroids[:, 1], marker='x', color='r');
			plt.setp(legend.get_title(), fontsize=10)
			plt.title('K-means clusters of weekly time-separated documents of all Trump-dense threads')
			plt.savefig('../visualisations/clusters_small_noaxes' + dateformat + '.png', dpi=200,bbox_inches='tight')

			plt.show()


def getWord2vecModel(train='', load='', modelname='', min_word=200):
	if train != '':
		print('Training ' + modelname)
		# train model
		# neighbourhood?
		model = Word2Vec(train, min_count=min_word)
		# pickle the entire model to disk, so we can load&resume training later
		model.save(modelname + '.model')
		#store the learned weights, in a format the original C tool understands
		model.wv.save_word2vec_format(modelname + '.model.bin')
		return model
	elif load != '':
		model = KeyedVectors.load_word2vec_format(load, binary=True)
		return model

def getFastTextModel(train='', load='', modelname='', min_word=200):
	if train != '':
		# train model
		print(train[:10])
		model = fasttext.FastText(sentences=train, min_count=min_word)
		model.save('word_embeddings/fasttext/models/' + modelname + '.model.bin')
		# pickle the entire model to disk, so we can load&resume training later
		return model
	elif load != '':
		model = fasttext.FastText.load('word_embeddings/fasttext/models/' + load)
		return model

def getGloveModel(train='', load='', modelname='', min_word=''):
	if train != '':
		# train model
		cooccur = glove.Corpus()
		cooccur.fit(train, window=5)
		# and train GloVe model itself, using 10 epochs
		model_glove = glove.Glove(no_components=100, learning_rate=0.05)
		model_glove.fit(cooccur.matrix, epochs=10)
		model_glove.save('word_embeddings/fasttext/models/' + modelname + '.model.bin')
		# pickle the entire model to disk, so we can load&resume training later
		return model
	elif load != '':
		model = fasttext.FastText.load('word_embeddings/fasttext/models/' + load)
		return model

def showPCAGraph(model):
	# use t-sne!
	# PCA is more effective for 'importance' of words

	# fit a 2d PCA model to the vectors
	X = model[model.wv.vocab]
	pca = PCA(n_components=80)
	result = pca.fit_transform(X)
	# create a scatter plot of the projection

	pyplot.scatter(result[:, 0], result[:, 1])
	words = list(model.wv.vocab)
	for i, word in enumerate(words):
		pyplot.annotate(word, xy=(result[i, 0], result[i, 1]), size=6)
	plt.rcParams.update({'font.size': 3})
	pyplot.show()

# some calls for these function come from substring
def getSimilaritiesFromCsv(df, modelname = ''):
	#df = pd.read_csv(csvdoc, encoding='utf-8')
	li_strings = []
	for comment in df['comment']:
		li_strings.append(comment)
	words_stemmed = getTokens(li_strings, similaritytype='words', stems=False)
	#print(words_stemmed[:100])
	#df_stemmedwords = pd.DataFrame(words_stemmed)

	pickle.dump(words_stemmed, open("word2vec/pickle_stems/pickle_" + modelname + ".p", "wb"))
	model = getWord2VecModel(train=words_stemmed, modelname=modelname)
	# model = getWord2VecModel(load=modelname)
	#showPCAGraph(model)
	# similars = model.most_similar(positive=['btfo'], topn = 20)
	# print(similars)
	# similars = model.similar_by_vector(model['hillari'] + model['polit'])
	# print(similars)

def getTsneScatterPlot(model, plottitle='', plotname='', perplexity=10, minword=.03, maxword=.005, highlightword=''):
	print('getting vocab')
	
	li_vocab = []
	li_counts = []
	di_wordcounts = {}
	print('getting words')
	for word in list(model.wv.vocab):
		li_counts.append(model.wv.vocab[word].count)
		di_wordcounts[word] = model.wv.vocab[word].count
	li_counts.sort(reverse=True)

	mincount = li_counts[int(len(li_counts) * minword)]
	maxcount = li_counts[int(len(li_counts) * maxword)]
	print(mincount, maxcount)
	print(li_counts[:10])
	print(sorted(di_wordcounts.items(), key=operator.itemgetter(1), reverse=True)[:50])
	
	for word in list(model.wv.vocab):
		if model.wv.vocab[word].count >= mincount and model.wv.vocab[word].count <= maxcount:
			if 'http' not in word and 'youtube' not in word and '.com' not in word:
				#print(word, model.wv.vocab[word])
				li_vocab.append(word)

	X = model[li_vocab]
	#TSNE args: perplexity=40, n_components=2, init='pca', n_iter=2500, random_state=23
	tsne = TSNE(n_components=2, perplexity=perplexity)
	print('fitting TSNE')
	X_tsne = tsne.fit_transform(X)
	print('writing DataFrame')
	df = pd.DataFrame(X_tsne, index=li_vocab, columns=['x', 'y'])
	print('creating plt figure')
	fig = plt.figure(figsize=(15, 13))
	ax = fig.add_subplot(1, 1, 1)

	scatter = ax.scatter(df['x'].tolist(), df['y'].tolist(), facecolors='none', edgecolors='none')
	labels = []
	for word, pos in df.iterrows():
		if word == highlightword and highlightword != '':
			highlightpos = pos
		# if 'haha' in word or 'lol' in word or 'reee' in word or 'lmfao' in word:
			ax.annotate(word, pos, fontsize=17, color='#3F902780')
			ax.set_zorder(1000)
		else:
			
			ax.annotate(word, pos, fontsize=8, color='#16161680')
			ax.set_zorder(10)
		labels.append(word)
	if highlightword != '':
		print('')
		ax.annotate(highlightword, highlightpos, fontsize=17, color='#E13131')
	#adjust_text(labels, force_text=0.05, arrowprops=dict(arrowstyle="-|>", color='gray', alpha=0.1))

	plt.title('t-SNE word2vec similarities for ' + plottitle + ', (min wordcount: ' + str(mincount) + ')')
	plt.show()
	#save the mpl figures to pickle and zoom in later
	pickle.dump(fig, open(r'word_embeddings/tsne/mpl_tsnescatterplot_' + plotname + '.p', 'wb'))
	css='*{font-family: Arial, sans-serif;}'
	tooltip2 = mpld3.plugins.PointHTMLTooltip(fig, css=css)
	mpld3.plugins.connect(fig, tooltip2)
	#add interactive labels
	tooltip = mpld3.plugins.PointLabelTooltip(scatter, labels=labels)
	mpld3.plugins.connect(fig, tooltip)
	mpld3.show()
	#save to html
	mpld3.save_html(fig, 'word_embeddings/tsne/mpl_tsnescatterplot_' + plotname + '.html')
	plt.savefig('word_embeddings/tsne/mpl_tsnescatterplot_' + plotname + '.png', dpi=200)
	#plt.savefig('C:/Users/hagen/Dropbox/Universiteit van Amsterdam/J2S2 Thesis/visualisations/tsne/mpl_tsnescatterplot_' + plotname + '.png', dpi=200)
	plt.gcf().clear()

def getsimilars(word, month):
	df_similars = pd.DataFrame()

	model = getWord2VecModel(load='word2vec/models/w2v_model_all-' + month + '.model')
	similars = model.wv.most_similar(positive=[word], topn = 30)
	df_similars[month] = [words[0] for words in similars]
	df_similars['ratio-' + month] = [int((words[1] * 100)) for words in similars]
	return df_similars

#split the words in 'comment' column of csv and return list of tokens
def createTokensFromCsv(file=''):
	li_allstrings = []

	folder = 'substring_mentions/mentions_trump/months/'
	df = pd.read.csv(file, encoding='utf-8')
	for comment in df['comment']:
		comment = ' '.join(comment)
		li_allstrings.append(li_comments)
	return li_allstrings

def returnNonStemmed(textinput):
	di_stems = pickle.load(open('di_stems.p', 'rb'))
	li_nonstemmed = []
	
	#handle both strings and lists (numpy and regular)
	if type(textinput) != str:
		for word in textinput:
			if word in di_stems:
				word_nonstemmed = di_stems[word][0]
				li_nonstemmed.append(word_nonstemmed)
			else:
				li_nonstemmed.append(word)
	else:
		if textinput in di_stems:
			word_nonstemmed = di_stems[textinput][0]
			return word_nonstemmed
		else:
			return textinput
	return li_nonstemmed

def getW2vCosineDistance(word1, word2, plot=False):
	di_cos_dist = OrderedDict([('06-2015', 0),('07-2015', 0),('08-2015', 0),('09-2015', 0),('10-2015', 0),('11-2015',0),('12-2015', 0),('01-2016', 0),('02-2016', 0),('03-2016', 0),('04-2016', 0),('05-2016', 0),('06-2016', 0),('07-2016', 0),('08-2016', 0),('09-2016', 0),('10-2016', 0),('11-2016', 0),('12-2016', 0),('01-2017', 0),('02-2017', 0),('03-2017', 0),('04-2017', 0),('05-2017', 0),('06-2017', 0),('07-2017', 0),('08-2017', 0),('09-2017', 0),('10-2017', 0),('11-2017', 0),('12-2017', 0),('01-2018', 0),('02-2018', 0),('03-2018', 0)])

	folder = 'word_embeddings/word2vec/models/allwords/'
	for file in os.listdir(folder):
		if 'bin' not in file and 'trainables' not in file and 'vectors' not in file:
			print('Loading ' + file)
			model = getWord2vecModel(load=folder + file)
			if word2 in model.wv.vocab:
				sim = model.similarity(word1, word2)
				print(sim)
				di_cos_dist[file[14:-6:]] = sim
			else:
				di_cos_dist[file[14:-6:]] = 0
	print(di_cos_dist)

	if plot == True:
		createCosineDistHisto(di_cos_dist, word1, word2)

	return di_cos_dist

def getW2vSims(inputmodel, querystring='kek', longitudinal=False, nearest_neighbours=10):
	""" returns a json file of word2vec nearest neighbours """
	model = getWord2vecModel(load=inputmodel)

	if querystring not in list(model.wv.vocab):
		return 'Word not in vocabulary'
	else:
		neigbours = model.most_similar(positive=[querystring], topn=nearest_neighbours)
	print(neigbours)

	#create the JSON file required for the D3 network graph
	di_nn = {}
	di_nn['nodes'] = []
	di_nn['links'] = []

	di_nn['nodes'].append({'name': 'empty'})
	di_nn['nodes'][0]['name'] = querystring
	di_nn['nodes'][0]['group'] = 1

	for index, neigbour in enumerate(neigbours):
		#create nodes
		di_nn['nodes'].append({'name': 'empty'})
		di_nn['nodes'][index + 1]['name'] = neigbour[0]
		di_nn['nodes'][index + 1]['group'] = 1
		#create edges
		di_nn['links'].append({'source': 'empty'})
		di_nn['links'][index]['source'] = index + 1
		di_nn['links'][index]['target'] = 0
		di_nn['links'][index]['weight'] = neigbour[1]

	jsonfile = json.dumps(di_nn)
	print(jsonfile)
	return jsonfile


#getW2vSims('static/data/word_embeddings/test.model', querystring='trump', longitudinal=False)
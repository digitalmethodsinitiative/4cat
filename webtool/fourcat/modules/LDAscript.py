from nltk.tokenize import RegexpTokenizer
from stop_words import get_stop_words
from nltk.stem.porter import PorterStemmer
from gensim import corpora, models
import gensim



def createLDAtopics(di_input):

	di_threadstrings = di_input
	tokenizer = RegexpTokenizer(r'\w+')

	# create English stop words list
	en_stop = get_stop_words('en')

	# Create p_stemmer of class PorterStemmer
	p_stemmer = PorterStemmer()
	
	# compile sample documents into a list
	thread_set = []

	for key, threadstring in di_threadstrings.items():
		thread_set.append(threadstring)

	# list for tokenized documents in loop
	texts = []

	# loop through document list
	for i in thread_set:
	    
	    # clean and tokenize document string
	    raw = i.lower()
	    tokens = tokenizer.tokenize(raw)

	    # remove stop words from tokens
	    stopped_tokens = [i for i in tokens if not i in en_stop]
	    
	    # stem tokens
	    stemmed_tokens = [p_stemmer.stem(i) for i in stopped_tokens]
	    
	    # add tokens to list
	    texts.append(stemmed_tokens)

	# turn our tokenized documents into a id <-> term dictionary
	dictionary = corpora.Dictionary(texts)
	    
	# convert tokenized documents into a document-term matrix
	corpus = [dictionary.doc2bow(text) for text in texts]

	# generate LDA model
	ldamodel = gensim.models.ldamodel.LdaModel(corpus, num_topics=10, id2word = dictionary, passes=20)

	# output a result
	print(ldamodel.print_topics(num_topics=10, num_words=5))
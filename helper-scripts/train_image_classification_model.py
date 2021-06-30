"""
This script builds Convolutional Neural Networks (CNNs) to compare to sets of
images and attempts to use features found unique in either set to classify
future images.

You will need to separate your images into a folder structure as follows:

- main_dir
    - class_A_name
    - class_B_name

Class B will be the "target" class represented by a 1, while A will be a 0.

The script will then create a temporary folder structure and train/test split.

It will then save a model and print and save the evaluation results. You will
then need to add the model the models folder and update
processors/metrics/xception_image_classification.py appropriately

# Addtional information on how the model works

On layers:
Convolutional layers separate the groups pixels by location and applies a
numeric filter to them. This can essentially identify edges. The MaxPooling
layer then reduces the dimensionality and identifies high areas of change (again
detecting edges). This is applied across all three colors in a color photo. This
is performed at varying levels of granularity.

The Flatten layer reduces the image to one dimension which then is run through
a Dense layer where every pixel is connected to every other pixel.

On activation functions:
Read this article https://machinelearningmastery.com/rectified-linear-activation-function-for-deep-learning-neural-networks/

The rectified linear activation or ReLU function "fires" an individual
perceptron (neuron) and allows back propogation (later results updating the
weights of earlier perceptrons and affecting whether or not they "fire"). This
function works well through most stages of the model.

The sigmoid function is a logistic regression that produces values from 0 to 1.
It therefore works as a probability and is out last output representing the
probability of the image being class A (0) or class B (1).
"""

# All images will be resized to the same shape
# Tested with 64, 64 which is the basis of the Conv2D layers
# I am not sure what happens if you do not use a square
img_width, img_height = 64, 64

# Main directory
main_dir = 'images/'
# These names should be the folder names of the respective classes
class_A_name = 'not_pepe'
class_B_name = 'pepe'
# What would you like to save your model as
model_save_as_name = 'simple_model_V3'

# Import libraries
import os
from pathlib import Path
import tempfile
import shutil
import time
import random
import numpy as np
import tensorflow as tf
from tensorflow.keras.models import Sequential
from tensorflow.keras import layers

# Helper functions
def train_test_split(list_of_filenames, percent_held_as_test=.1):
    files = list_of_filenames.copy()
    num_to_test = round(len(files) * percent_held_as_test)

    # Randomize
    random.shuffle(files)

    return files[:-num_to_test], files[-num_to_test:]

def make_temp_files(target_dir, original_dir, files_to_move):
    for file in files_to_move:
        shutil.copyfile(original_dir.joinpath(file), target_dir.joinpath(file))

#########
# Model #
#########

# Initialising the CNN
model = Sequential()

# Create convolutional layer. There are 3 color dimensions for input shape
model.add(layers.Conv2D(32, (3, 3), activation = 'relu', input_shape=(img_width, img_height, 3)))
# Pooling layer
model.add(layers.MaxPooling2D((2, 2)))

# 2nd convolutional layer
model.add(layers.Conv2D(32, (3, 3), activation = 'relu', input_shape = (img_width, img_height,  3)))
# 2nd pooling layer
model.add(layers.MaxPooling2D((2, 2)))

# Adding a 3rd convolutional layer with 64 filters
model.add(layers.Conv2D(64, (3, 3), activation = 'relu', input_shape = (img_width, img_height,  3)))
# 3rd pooling layer
model.add(layers.MaxPooling2D((2, 2)))

# Adding a 4th convolutional layer with 128 filters
model.add(layers.Conv2D(128, (3, 3), activation = 'relu', input_shape = (img_width, img_height,  3)))
# 4th pooling layer
model.add(layers.MaxPooling2D((2, 2)))

# Flattening into one demention
model.add(layers.Flatten())
# Full connection layers
model.add(layers.Dense(units = 512, activation = 'relu'))
# Final binary layer for category
model.add(layers.Dense(units = 1, activation = 'sigmoid'))

# Compiling the CNN
# Could try different optimizers and, possibly, loss functions though binary_crossentropy seems likely the best for this type of problem
model.compile(loss = 'binary_crossentropy',
              optimizer = 'adam',
              metrics = ['acc'])

##########################
# Import training images #
##########################

# TODO: Swap out keras preprocessing that expects images separated into
# directories so we can skip all the temporary files stuff!

# Split images into training and testing groups and move files into temporary directory tree
tempdirpath = tempfile.mkdtemp()

# Make folders
os.makedirs(Path(tempdirpath, 'train', class_A_name))
os.makedirs(Path(tempdirpath, 'train', class_B_name))
os.makedirs(Path(tempdirpath, 'test', class_A_name))
os.makedirs(Path(tempdirpath, 'test', class_B_name))

# Record training and testing folder paths
train_data_dir = Path(tempdirpath, 'train')
validation_data_dir = Path(tempdirpath, 'test')

# Collect filenames
class_A_files = os.listdir(Path(main_dir, class_A_name))
class_B_files = os.listdir(Path(main_dir, class_B_name))

# Split files into train test groups
class_A_train, class_A_test = train_test_split(class_A_files)
class_B_train, class_B_test = train_test_split(class_B_files)

# Move images to temporary structure
make_temp_files(Path(tempdirpath, 'train', class_A_name), Path(main_dir, class_A_name), class_A_train)
make_temp_files(Path(tempdirpath, 'test', class_A_name), Path(main_dir, class_A_name), class_A_test)
make_temp_files(Path(tempdirpath, 'train', class_B_name), Path(main_dir, class_B_name), class_B_train)
make_temp_files(Path(tempdirpath, 'test', class_B_name), Path(main_dir, class_B_name), class_B_test)

# Preprocessing
training_set = tf.keras.preprocessing.image_dataset_from_directory(
    train_data_dir,
    labels="inferred",
    label_mode="int",
    class_names=None,
    color_mode="rgb",
    batch_size=32,
    image_size=(img_width, img_height),
    shuffle=True,
    seed=None,
    validation_split=None,
    subset=None,
    interpolation="bilinear",
    follow_links=False,
    smart_resize=False,
)

val_set = tf.keras.preprocessing.image_dataset_from_directory(
    validation_data_dir,
    labels="inferred",
    label_mode="int",
    class_names=None,
    color_mode="rgb",
    batch_size=32,
    image_size=(img_width, img_height),
    shuffle=True,
    seed=None,
    validation_split=None,
    subset=None,
    interpolation="bilinear",
    follow_links=False,
    smart_resize=False,
)

###############
# Train model #
###############

start = time.time()
# Fitting the CNN
history = model.fit_generator(training_set,
#                               steps_per_epoch = nb_train_samples // batch_size,
                              epochs = 10,
#                               callbacks = early_stopping,
                              validation_data = val_set,
#                               validation_steps=nb_validation_samples // batch_size
                             )
print('Total time to complete training (minutes):', (time.time()-start)/60)

model.save(model_save_as_name)
print('Model saved as:', model_save_as_name)

###################
# Evalutate model #
###################

predictions = []
labels = []
for image_batch, label_batch in val_set:
    for image in image_batch:
        image = np.expand_dims(image, axis=0)
        predictions.append(model.predict(image))
    for label in label_batch:
        labels.append(label)

# There are built in functions to do this but I got OCD when I couldn't get one
# to work
true_positive = 0
true_negative = 0
false_positive = 0
false_negative = 0
for i in range(len(predictions)):
    pred = round(predictions[i][0][0])
    label = labels[i]

    if label == 1 and pred == 1:
        true_positive += 1
    elif label == 1 and pred == 0:
        false_negative += 1
    elif label == 0 and pred == 0:
        true_negative += 1
    elif label == 0 and pred == 1:
        false_positive += 1
    else:
        print('wtf')

print('TP', true_positive, '|', 'FN', false_negative)
print('FP' , false_positive, '|', 'TN', true_negative)
print('Sensitivity (TP/(TP + FN)) or', class_B_name, true_positive/(true_positive + false_negative))
print('Specificity (TN/(TN + FP)) or', class_A_name, true_negative/(true_negative + false_positive))

with open(model_save_as_name + 'eval_results.txt', 'w') as file:
    file.write(f"""
    Model name: {model_save_as_name}
    TP: {true_positive} | FN: {false_negative}\n
    FP: {false_positive} | TN {true_negative}\n
    Sensitivity (TP/(TP + FN)) or {class_B_name}: {true_positive/(true_positive + false_negative)}\n
    Specificity (TN/(TN + FP)) or {class_A_name}: {true_negative/(true_negative + false_positive)}\n
    """)

print("Job's done")

# Don't forget to delete all those temporary files
shutil.rmtree(tempdirpath)

import os
import numpy as np
import tensorflow as tf

'''
import keras
from keras import Input
from keras import layers
from keras.layers import Dense
from keras.layers import Activation
from keras.layers import Flatten
from keras.layers import Conv2D, ConvLSTM2D, UpSampling2D
from keras.layers import MaxPooling2D
from keras.layers import GlobalMaxPooling2D
from keras.layers import ZeroPadding2D
from keras.layers import AveragePooling2D
from keras.layers import GlobalAveragePooling2D, LSTM, Add
from keras.layers import BatchNormalization, TimeDistributed, Reshape
from keras.models import Model
from keras.preprocessing import image
from keras import backend as K
from keras.utils import layer_utils
from keras.utils.data_utils import get_file
from keras.applications.imagenet_utils import decode_predictions
from keras.applications.imagenet_utils import preprocess_input
'''

import tensorflow.keras as keras
from tensorflow.keras import Input
from tensorflow.python.keras import layers
from tensorflow.python.keras.layers import Dense
from tensorflow.python.keras.layers import Activation
from tensorflow.python.keras.layers import Flatten
from tensorflow.python.keras.layers import Conv2D, ConvLSTM2D, UpSampling2D
from tensorflow.python.keras.layers import MaxPooling2D
from tensorflow.python.keras.layers import GlobalMaxPooling2D
from tensorflow.python.keras.layers import ZeroPadding2D
from tensorflow.python.keras.layers import AveragePooling2D
from tensorflow.python.keras.layers import GlobalAveragePooling2D, LSTM, Add
from tensorflow.python.keras.layers import BatchNormalization, TimeDistributed, Reshape
from tensorflow.python.keras.models import Model
from tensorflow.python.keras.preprocessing import image
from tensorflow.python.keras import backend as K
from tensorflow.python.keras.utils import layer_utils
from tensorflow.python.keras.utils.data_utils import get_file
from tensorflow.python.keras.applications.imagenet_utils import decode_predictions
from tensorflow.python.keras.applications.imagenet_utils import preprocess_input


from modis_utils.generators import OneOutputGenerator
from modis_utils.misc import get_data_test, get_target_test, cache_data
from modis_utils.model.core import compile_model, conv_lstm_2D, conv_2D
from modis_utils.model.loss_function import mse_with_mask, mse_with_mask_batch
from modis_utils.model.eval import predict_and_visualize_by_data_file_one_output
from modis_utils.image_processing import mask_lake_img


class ResnetLSTMSingleOutput:
    
    def get_generator(data_filenames, batch_size, original_batch_size, pretrained):
        return OneOutputGenerator(data_filenames, batch_size, original_batch_size, pretrained)

    def create_model(modis_utils_obj):
        crop_size = modis_utils_obj._crop_size
        input_timesteps = modis_utils_obj._input_timesteps
        output_timesteps = modis_utils_obj._output_timesteps
        compile_params = modis_utils_obj._compile_params
        weights = modis_utils_obj._pretrained
        return ResnetLSTMSingleOutput._create_model(
            crop_size, crop_size, input_timesteps, compile_params, weights)
    
    def _create_model(img_height, img_width, input_timesteps, compile_params, weights):
        if weights == True:
            weights = 'imagenet'
            channels = 3
        else:
            weights = None
            channels = 1
        # Prepair
        input_shape = (input_timesteps, img_height, img_width, channels)

        # Model architecture
        source = Input(
            name='seed', shape=input_shape, dtype=tf.float32)
        
        resnet_encoder_block = resnet_encoder(input_shape=input_shape[1:], weights=weights)
        net = TimeDistributed(resnet_encoder_block)(source)
        
        net = ConvLSTM2D(filters=128, kernel_size=3, padding='same', return_sequences=True)(net)
        net = BatchNormalization()(net)
        net = ConvLSTM2D(filters=1, kernel_size=3, padding='same', return_sequences=False)(net)
        net = BatchNormalization()(net)
        #net = Reshape(target_shape=(64, 64, 1))(net)
        
        resnet_decoder = resnet_up(net)
        predicted_img = Activation('sigmoid')(resnet_decoder)
        
        model = Model(inputs=[source], outputs=[predicted_img])
        
        # Compile model
        model = compile_model(model, compile_params)
        return model 

    def inference(modis_utils_obj, data_type, idx):
        file_path = modis_utils_obj._data_files[data_type]['data']
        data_test = get_data_test(file_path, idx)
        data_test = np.expand_dims(np.expand_dims(data_test, axis=0), axis=-1)
        if modis_utils_obj._pretrained:
            data_test = np.tile(data_test, 3)
        output = modis_utils_obj.inference_model.predict(data_test)
        output = np.squeeze(np.squeeze(output, axis=0), axis=-1)
        return output

    def eval(modis_utils_obj, data_type, idx, metric):
        if metric is None:
            metric = mse_with_mask
        target_path = modis_utils_obj._data_files[data_type]['target']
        target = get_target_test(target_path, idx)
        mask_path = modis_utils_obj._data_files[data_type]['mask']
        mask = get_target_test(mask_path, idx)
        predict = modis_utils_obj.get_inference(data_type, idx)
        return metric(target, predict, mask)

    def visualize_result(modis_utils_obj, data_type, idx):
        data_file_path = modis_utils_obj._data_files[data_type]['data']
        target_file_path = modis_utils_obj._data_files[data_type]['target']
        pred = modis_utils_obj.get_inference(data_type, idx)
        predict_and_visualize_by_data_file_one_output(
            data_file_path, target_file_path, pred, idx, modis_utils_obj._result_dir)

    def create_predict_mask_lake(modis_utils_obj, data_type='test'):
        for idx in range(modis_utils_obj.get_n_tests(data_type)):
            pred = modis_utils_obj.get_inference(data_type, idx)
            pred = modis_utils_obj._preprocess_strategy_context.inverse(pred)
            predict_mask_lake_path = os.path.join(
                modis_utils_obj._predict_mask_lake_dir, data_type, '{}.dat'.format(idx))
            cache_data(mask_lake_img(pred), predict_mask_lake_path)


WEIGHTS_PATH = 'https://github.com/fchollet/deep-learning-models/releases/download/v0.2/resnet50_weights_tf_dim_ordering_tf_kernels.h5'
WEIGHTS_PATH_NO_TOP = 'https://github.com/fchollet/deep-learning-models/releases/download/v0.2/resnet50_weights_tf_dim_ordering_tf_kernels_notop.h5'

def identity_block(input_tensor, kernel_size, filters, stage, block):
    """The identity block is the block that has no conv layer at shortcut.

    # Arguments
        input_tensor: input tensor
        kernel_size: defualt 3, the kernel size of middle conv layer at main path
        filters: list of integers, the filterss of 3 conv layer at main path
        stage: integer, current stage label, used for generating layer names
        block: 'a','b'..., current block label, used for generating layer names

    # Returns
        Output tensor for the block.
    """
    filters1, filters2, filters3 = filters
    if K.image_data_format() == 'channels_last':
        bn_axis = 3
    else:
        bn_axis = 1
    conv_name_base = 'res' + str(stage) + block + '_branch'
    bn_name_base = 'bn' + str(stage) + block + '_branch'

    x = Conv2D(filters1, (1, 1), name=conv_name_base + '2a')(input_tensor)
    x = BatchNormalization(axis=bn_axis, name=bn_name_base + '2a')(x)
    x = Activation('relu')(x)

    x = Conv2D(filters2, kernel_size,
               padding='same', name=conv_name_base + '2b')(x)
    x = BatchNormalization(axis=bn_axis, name=bn_name_base + '2b')(x)
    x = Activation('relu')(x)

    x = Conv2D(filters3, (1, 1), name=conv_name_base + '2c')(x)
    x = BatchNormalization(axis=bn_axis, name=bn_name_base + '2c')(x)

    x = layers.add([x, input_tensor])
    x = Activation('relu')(x)
    return x


def conv_block(input_tensor, kernel_size, filters, stage, block, strides=(2, 2)):
    """conv_block is the block that has a conv layer at shortcut

    # Arguments
        input_tensor: input tensor
        kernel_size: defualt 3, the kernel size of middle conv layer at main path
        filters: list of integers, the filterss of 3 conv layer at main path
        stage: integer, current stage label, used for generating layer names
        block: 'a','b'..., current block label, used for generating layer names

    # Returns
        Output tensor for the block.

    Note that from stage 3, the first conv layer at main path is with strides=(2,2)
    And the shortcut should have strides=(2,2) as well
    """
    filters1, filters2, filters3 = filters
    if K.image_data_format() == 'channels_last':
        bn_axis = 3
    else:
        bn_axis = 1
    conv_name_base = 'res' + str(stage) + block + '_branch'
    bn_name_base = 'bn' + str(stage) + block + '_branch'

    x = Conv2D(filters1, (1, 1), strides=strides,
               name=conv_name_base + '2a')(input_tensor)
    x = BatchNormalization(axis=bn_axis, name=bn_name_base + '2a')(x)
    x = Activation('relu')(x)

    x = Conv2D(filters2, kernel_size, padding='same',
               name=conv_name_base + '2b')(x)
    x = BatchNormalization(axis=bn_axis, name=bn_name_base + '2b')(x)
    x = Activation('relu')(x)

    x = Conv2D(filters3, (1, 1), name=conv_name_base + '2c')(x)
    x = BatchNormalization(axis=bn_axis, name=bn_name_base + '2c')(x)

    shortcut = Conv2D(filters3, (1, 1), strides=strides,
                      name=conv_name_base + '1')(input_tensor)
    shortcut = BatchNormalization(axis=bn_axis, name=bn_name_base + '1')(shortcut)

    x = layers.add([x, shortcut])
    x = Activation('relu')(x)
    return x


def ResNet50(include_top=True, weights='imagenet',
             input_shape=None,
             pooling=None,
             classes=1000):
    """Instantiates the ResNet50 architecture.

    Optionally loads weights pre-trained
    on ImageNet. Note that when using TensorFlow,
    for best performance you should set
    `image_data_format="channels_last"` in your Keras config
    at ~/.keras/keras.json.

    The model and the weights are compatible with both
    TensorFlow and Theano. The data format
    convention used by the model is the one
    specified in your Keras config file.

    # Arguments
        include_top: whether to include the fully-connected
            layer at the top of the network.
        weights: one of `None` (random initialization)
            or "imagenet" (pre-training on ImageNet).
        input_tensor: optional Keras tensor (i.e. output of `layers.Input()`)
            to use as image input for the model.
        input_shape: optional shape tuple, only to be specified
            if `include_top` is False (otherwise the input shape
            has to be `(224, 224, 3)` (with `channels_last` data format)
            or `(3, 224, 244)` (with `channels_first` data format).
            It should have exactly 3 inputs channels,
            and width and height should be no smaller than 197.
            E.g. `(200, 200, 3)` would be one valid value.
        pooling: Optional pooling mode for feature extraction
            when `include_top` is `False`.
            - `None` means that the output of the model will be
                the 4D tensor output of the
                last convolutional layer.
            - `avg` means that global average pooling
                will be applied to the output of the
                last convolutional layer, and thus
                the output of the model will be a 2D tensor.
            - `max` means that global max pooling will
                be applied.
        classes: optional number of classes to classify images
            into, only to be specified if `include_top` is True, and
            if no `weights` argument is specified.

    # Returns
        A Keras model instance.

    # Raises
        ValueError: in case of invalid argument for `weights`,
            or invalid input shape.
    """
    if weights not in {'imagenet', None}:
        raise ValueError('The `weights` argument should be either '
                         '`None` (random initialization) or `imagenet` '
                         '(pre-training on ImageNet).')

    if weights == 'imagenet' and include_top and classes != 1000:
        raise ValueError('If using `weights` as imagenet with `include_top`'
                         ' as true, `classes` should be 1000')

    img_input = Input(shape=input_shape)
    if K.image_data_format() == 'channels_last':
        bn_axis = 3
    else:
        bn_axis = 1

    x = ZeroPadding2D((3, 3))(img_input)
    x = Conv2D(64, (7, 7), strides=(2, 2), name='conv1')(x)
    x = BatchNormalization(axis=bn_axis, name='bn_conv1')(x)
    x = Activation('relu')(x)
    x = MaxPooling2D((3, 3), strides=(2, 2))(x)

    x = conv_block(x, 3, [64, 64, 256], stage=2, block='a', strides=(1, 1))
    x = identity_block(x, 3, [64, 64, 256], stage=2, block='b')
    x = identity_block(x, 3, [64, 64, 256], stage=2, block='c')

    x = conv_block(x, 3, [128, 128, 512], stage=3, block='a')
    x = identity_block(x, 3, [128, 128, 512], stage=3, block='b')
    x = identity_block(x, 3, [128, 128, 512], stage=3, block='c')
    x = identity_block(x, 3, [128, 128, 512], stage=3, block='d')

    x = conv_block(x, 3, [256, 256, 1024], stage=4, block='a')
    x = identity_block(x, 3, [256, 256, 1024], stage=4, block='b')
    x = identity_block(x, 3, [256, 256, 1024], stage=4, block='c')
    x = identity_block(x, 3, [256, 256, 1024], stage=4, block='d')
    x = identity_block(x, 3, [256, 256, 1024], stage=4, block='e')
    x = identity_block(x, 3, [256, 256, 1024], stage=4, block='f')

    x = conv_block(x, 3, [512, 512, 2048], stage=5, block='a')
    x = identity_block(x, 3, [512, 512, 2048], stage=5, block='b')
    x = identity_block(x, 3, [512, 512, 2048], stage=5, block='c')

    x = AveragePooling2D((7, 7), name='avg_pool')(x)

    if include_top:
        x = Flatten()(x)
        x = Dense(classes, activation='softmax', name='fc1000')(x)
    else:
        if pooling == 'avg':
            x = GlobalAveragePooling2D()(x)
        elif pooling == 'max':
            x = GlobalMaxPooling2D()(x)
    
    inputs = img_input
    # Create model.
    model = Model(inputs, x, name='resnet50')

    # load weights
    if weights == 'imagenet':
        if include_top:
            weights_path = get_file('resnet50_weights_tf_dim_ordering_tf_kernels.h5',
                                    WEIGHTS_PATH,
                                    cache_subdir='models',
                                    md5_hash='a7b3fe01876f51b976af0dea6bc144eb')
        else:
            weights_path = get_file('resnet50_weights_tf_dim_ordering_tf_kernels_notop.h5',
                                    WEIGHTS_PATH_NO_TOP,
                                    cache_subdir='models',
                                    md5_hash='a268eb855778b3df3c7506639542a6af')
        model.load_weights(weights_path)
        if K.backend() == 'theano':
            layer_utils.convert_all_kernels_in_model(model)

        if K.image_data_format() == 'channels_first':
            if include_top:
                maxpool = model.get_layer(name='avg_pool')
                shape = maxpool.output_shape[1:]
                dense = model.get_layer(name='fc1000')
                layer_utils.convert_dense_weights_data_format(dense, shape, 'channels_first')

            if K.backend() == 'tensorflow':
                warnings.warn('You are using the TensorFlow backend, yet you '
                              'are using the Theano '
                              'image data format convention '
                              '(`image_data_format="channels_first"`). '
                              'For best performance, set '
                              '`image_data_format="channels_last"` in '
                              'your Keras config '
                              'at ~/.keras/keras.json.')
    return model

def resnet_encoder(input_shape, weights=None):
    inputs = Input(shape=input_shape)
    resnet_encoder = ResNet50(include_top=False, weights=weights, input_shape=input_shape)(inputs)
    resnet_encoder = Flatten()(resnet_encoder)
    encode_shape = (input_shape[0]//4, input_shape[1]//4)
    resnet_encoder = Dense(encode_shape[0]*encode_shape[1])(resnet_encoder)
    resnet_encoder = Reshape(target_shape=(encode_shape[0], encode_shape[1], 1))(resnet_encoder)
    model = Model(inputs, resnet_encoder, name='resnet_encoder')
    if weights:
        for layer in model.layers[:-3]:
            layer.trainable = False
    return model


##
## SR CNN
##
def create_srcnn_model(input_shape, scale=4):
    inputs = Input(shape=input_shape)

    # 9-5-5 (see paper)
    x = UpSampling2D((scale, scale))(inputs) # upsample
    x = Conv2D(64, (9, 9), activation='relu', padding='same', name='level1')(x)
    x = Conv2D(32, (5, 5), activation='relu', padding='same', name='level2')(x)
    x = Conv2D(3, (5, 5), activation='relu', padding='same', name='level3')(x)

    m = Model(inputs=inputs, outputs=x)
    return m

##
## SR filter blocks
##
def conv_block_1(inputs, filters, kernel_size, strides=(1,1), padding="same", activation='relu'):
    x = Conv2D(filters, kernel_size, strides=strides, padding=padding)(inputs)
    x = BatchNormalization()(x)
    if activation:
        x = Activation(activation)(x)
    return x

def up_block(inputs, filters, kernel_size, strides=(1,1), scale=2, padding="same", activation="relu"):
    size = (scale,scale)
    x = UpSampling2D(size)(inputs)
    x = Conv2D(filters, kernel_size, strides=strides, padding=padding)(x)
    x = BatchNormalization()(x)
    x = Activation(activation)(x)
    return x

def res_block(inputs, filters=64):
    x = conv_block_1(inputs, filters, (3,3))
    x = conv_block_1(x, filters, (3,3), activation=False)
    return Add()([x, inputs])


##
## Resnet batchnorm w/ NN upsampling
##

def resnet_up(inputs, scale=4):
    x = conv_block_1(inputs, 64, (9,9))
    for i in range(4): x = res_block(x)
    x = up_block(x, 64, (3, 3), scale=scale / 2)
    x = up_block(x, 64, (3, 3), scale=scale / 2)
    out = Conv2D(1, (9,9), activation='relu', padding='same')(x)
    return out
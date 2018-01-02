from __future__ import print_function

import keras.backend as K
import keras.losses as losses
import keras.optimizers as optimizers
import numpy as np

from keras.callbacks import ModelCheckpoint
from keras.layers.advanced_activations import LeakyReLU
from keras.layers import Input, RepeatVector, Reshape
from keras.layers.embeddings import Embedding
from keras.layers.merge import Concatenate, Multiply
from keras.losses import binary_crossentropy
from keras.models import Model, Sequential
from keras.optimizers import Adam
from matplotlib import pyplot as plt

from .abstract import *
from .callbacks import *
from .robot_multi_models import *
from .split import *
from .mhp_loss import *
from .loss import *
from .sampler2 import *


class ConditionalImage(PredictionSampler2):
    '''
    Version of the sampler that only produces results conditioned on a
    particular action; this version does not bother trying to learn a separate
    distribution for each possible state.

    This one generates:
      - image
      - arm command
      - gripper command

    '''

    def __init__(self, *args, **kwargs):
        '''
        As in the other models, we call super() to parse arguments from the
        command line and set things like our optimizer and learning rate.

        Parameters:
        -----------
        taskdef: definition of the problem used to create a task model
        '''
        super(ConditionalImage, self).__init__(*args, **kwargs)
        self.PredictorCb = ImageCb
        self.rep_size = 128
        self.num_transforms = 3
        self.add_disc = True

    def _makePredictor(self, features):
        # =====================================================================
        # Create many different image decoders
        image_outs = []
        arm_outs = []
        gripper_outs = []
        train_outs = []
        label_outs = []
        
        (images, arm, gripper) = features
        img_shape, image_size, arm_size, gripper_size = self._sizes(
                images,
                arm,
                gripper)

        # =====================================================================
        # Load the image decoders
        img_in = Input(img_shape,name="predictor_img_in")
        arm_in = Input((arm_size,))
        gripper_in = Input((gripper_size,))
        arm_gripper = Concatenate()([arm_in, gripper_in])
        label_in = Input((1,))
        ins = [img_in]

        encoder = self._makeImageEncoder(img_shape)
        try:
            encoder.load_weights(self._makeName(
                "pretrain_image_encoder_model",
                "image_encoder.h5f"))
            encoder.trainable = self.retrain
        except Exception as e:
            pass

        if self.skip_connections:
            decoder = self._makeImageDecoder(self.hidden_shape,self.skip_shape)
        else:
            decoder = self._makeImageDecoder(self.hidden_shape)
        try:
            decoder.load_weights(self._makeName(
                "pretrain_image_encoder_model",
                "image_decoder.h5f"))
            decoder.trainable = self.retrain
        except Exception as e:
            pass

        rep_channels = self.encoder_channels

        # =====================================================================
        # Load the arm and gripper representation

        h = encoder(ins)
        value_out, next_option_out = GetNextOptionAndValue(h,
                                                           self.num_options,
                                                           self.rep_size,
                                                           dropout_rate=self.dropout_rate,
                                                           option_in=label_in)

        # create input for controlling noise output if that's what we decide
        # that we want to do
        if self.use_noise:
            z = Input((self.num_hypotheses, self.noise_dim))
            ins += [z]

        next_option_in = Input((48,), name="next_option_in")
        ins += [next_option_in]

        #y = OneHot(self.num_options)(next_option_in)
        #y = Flatten()(y)
        y = next_option_in
        x = h

        x = TileOnto(x, y, self.num_options, (8,8))
        x = AddConv2D(x, self.tform_filters*2, [1,1], 2, 0.)
        # Process
        for i in range(self.num_transforms):
            x = TileOnto(x, y, self.num_options, (4,4))
            x = AddConv2D(x, self.tform_filters*2,
                    self.tform_kernel_size,
                    stride=1,
                    dropout_rate=self.tform_dropout_rate)

        x = AddConv2DTranspose(x,
                self.tform_filters*2,
                self.tform_kernel_size,
                stride=2,
                dropout_rate=0.)

        x = AddConv2D(x, rep_channels, [1, 1], stride=1,
                dropout_rate=0.)
        image_out = decoder(x)


        if self.add_disc:
            image_discriminator = self._makeImageEncoder(img_shape, disc=True)
            o1 = image_discriminator(ins[0])
            o2 = image_discriminator(image_out)
            o2.trainable = False

        # =====================================================================
        # Create models to train
        predictor = Model(ins + [label_in],
                [image_out, next_option_out, value_out])
        actor = GetActorModel(h, self.num_options, arm_size, gripper_size,
                self.decoder_dropout_rate)
        actor.compile(loss="mae",optimizer=self.getOptimizer())
        arm_cmd, gripper_cmd = actor([h, next_option_in])
        train_predictor = Model(ins + [label_in],
                [image_out, next_option_out, value_out, o1, o2,
                    arm_cmd,
                    gripper_cmd])
        predictor.compile(
                loss=["mae", "categorical_crossentropy", "mae"],
                loss_weights=[1., 0.1, 0.1,],
                optimizer=self.getOptimizer())
        train_predictor.compile(
                loss=["mae", "categorical_crossentropy", "mae",
                    "categorical_crossentropy", "categorical_crossentropy",
                    "mae", "mae"],
                loss_weights=[1., 0.1, 0.1, 1., 1e-4, 0.1, 0.02],
                #loss_weights=[1., 0.1, 0.1, 0.1, 0.02],
                optimizer=self.getOptimizer())
        actor.summary()
        train_predictor.summary()
        return predictor, train_predictor, actor, ins, h

    def _getData(self, *args, **kwargs):
        features, targets = self._getAllData(*args, **kwargs)
        [I, q, g, oin, q_target, g_target,] = features
        tt, o1, v, qa, ga, I_target = targets
        oin_1h = np.squeeze(self.toOneHot2D(oin, self.num_options))
        qa = np.squeeze(qa)
        ga = np.squeeze(ga)
        if self.use_noise:
            noise_len = features[0].shape[0]
            z = np.random.random(size=(noise_len,self.num_hypotheses,self.noise_dim))
            return [I, z, o1, oin], [ I_target, o1, v, oin_1h, o1, qa, ga]
            #return [I, z, o1, oin], [ I_target, o1, v, qa, ga]
        else:
            return [I, o1, oin], [ I_target, o1, v, oin_1h, o1, qa, ga]
            #return [I, o1, oin], [ I_target, o1, v, qa, ga]


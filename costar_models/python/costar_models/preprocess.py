from __future__ import print_function

import numpy as np

def RemoveBadExamples(datasets, reward, labels, reward_threshold=0):
    '''
    Remove negative examples from data set, i.e. examples where reward is below
    the given threshold at the end of the trial.

    Parameters:
    -----------
    datasets: list of numpy matrices fed into model
    reward: used to prune negative examples
    labels: ID of example; if last entry is negative remove
    reward_threshold: assume values with terminal reward less than this are bad
                      and need to be removed.
    '''
    max_label = max(labels)
    min_label = min(labels)

    new_data = []

    next_idx = np.zeros((len(datasets),),dtype=int)
    length = datasets[0].shape[0]
    good_labels = []
    for label in xrange(min_label, max_label+1):

        # prune any rewards that are not acceptable here. we assume that we
        # care the most about the terminal reward -- if the terminal reward is
        # not greater than zero, we will throw out the example
        if reward is not None and reward[labels==label][-1] < reward_threshold:
            # Since this was too low, just skip it
            print("<< skipping example ", label, "with reward =",
                    reward[labels==label][-1])
            good = False
            print("entries:", np.sum(labels==label))
            length -= np.sum(labels==label)
        else:
            print(">> including example ", label, "with reward =",
                    reward[labels==label][-1])
            good = True
            good_labels.append(label)

    for idx, data in enumerate(datasets):
        new_data.append(np.zeros((length,) + data.shape[1:]))
        print(idx, new_data[-1].shape)
    for label in good_labels:
        llen =  np.sum(labels==label)
        for idx, data in enumerate(datasets):
            subset = data[labels==label]
            new_data[idx][next_idx[idx]:next_idx[idx]+llen] = subset
            next_idx[idx]+=llen
    return new_data



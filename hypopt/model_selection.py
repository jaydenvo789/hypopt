
# coding: utf-8

# In[ ]:


# Python 2 and 3 compatibility
from __future__ import print_function, absolute_import, division, unicode_literals, with_statement

# Imports
import inspect
from sklearn.model_selection import ParameterGrid
from sklearn.model_selection import GridSearchCV
from sklearn.metrics import accuracy_score
import numpy as np
import warnings

# For parallel processing
import multiprocessing as mp
from multiprocessing import Pool
max_threads = mp.cpu_count()


# In[ ]:


# Analyze results in parallel on all cores.
def _run_thread_job(params):  
    try:
        job_params, model_params = params
        model = job_params["model"]
        
        # Seeding may be important for fair comparison of param settings.
        np.random.seed(seed = 0)
        if hasattr(model, 'seed') and not callable(model.seed): 
            model.seed = 0
        if hasattr(model, 'random_state') and not callable(model.random_state): 
            model.random_state = 0
            
        model.set_params(**model_params)    
        model.fit(job_params["X_train"], job_params["y_train"])
        
        if hasattr(model, 'score'):        
            score = model.score(job_params["X_val"], job_params["y_val"])
        else:            
            score = accuracy_score(y_val, model.predict(job_params["X_val"]))
        return (model, score)

    except Exception as e:
        # Supress warning
#         warnings.warn('ERROR in thread' + str(mp.current_process()) + "with exception:\n" + str(e))
        return None

def _parallel_param_opt(lst, threads=max_threads):
    pool = mp.Pool(threads)
    results = pool.map(_run_thread_job, lst)
    pool.close()
    pool.join()
    return results


# In[ ]:


from sklearn.base import BaseEstimator
class GridSearch(BaseEstimator):
    '''docstring

    Parameters
    ----------

    model : class inheriting sklearn.base.BaseEstimator
        The classifier whose hyperparams you need to optimize with grid search.
        The model must have model.fit(X,y) and model.predict(X) defined. Although it can
        work without it, its best if you also define model.score(X,y) so you can decide
        the scoring function for deciding the best parameters. If you are using an
        sklearn model, everything will work out of the box. To use a model from a 
        different library is no problem, but you need to wrap it in a class and
        inherit sklearn.base.BaseEstimator as seen in:
        https://github.com/cgnorthcutt/hyperopt 

    num_threads : int (chooses max # of threads by default),
        The number of CPU threads to use.

    cv_folds : int (default 3)
        The number of cross-validation folds to use if no X_val, y_val is specified.

    seed : int (default 0)
        Calls np.random.seed(seed = seed)'''


    def __init__(self, model, num_threads = max_threads, cv_folds = 3, seed = 0):
        self.model = model
        self.num_threads = num_threads
        self.cv_folds = cv_folds
        self.seed = seed
        np.random.seed(seed = seed)
        
        # Pre-define attributes for access after .fit() is called
        self.param_scores = None
        self.best_params = None
        self.best_score = None
        self.params = None
        self.scores = None
        
    
    def fit(
        self,
        X_train,
        y_train,
        param_grid,
        X_val = None, # validation data if it exists (if None, use crossval)
        y_val = None, # validation labels if they exist (if None, use crossval)
        verbose = True,
    ):
        '''Returns the model trained with the hyperparameters that maximize accuracy
        on the (X_val, y_val) validation data (if specified), else the parameters
        that maximize cross fold validation score. Uses grid search to find the best
        hyper-parameters.

        Parameters
        ----------

        X_train : np.array of shape (n, m)
            The training data.

        y_train : np.array of shape (n,) or (n, 1)
            The training labels. They can be noisy if you use model = RankPruning().

        param_grid : dict
            The parameters to train with out on the validation set. Dictionary with
            parameters names (string) as keys and lists of parameter settings to try
            as values, or a list of such dictionaries, in which case the grids spanned
            by each dictionary in the list are explored. This enables searching over
            any sequence of parameter settings. Format is:
            {'param1': ['list', 'of', 'options'], 'param2': ['l', 'o', 'o'], ...}\
            For an example, check out:
            scikit-learn.org/stable/modules/generated/sklearn.model_selection.ParameterGrid.html

        X_val : np.array of shape (n0, m)
            The validation data to optimize paramters with. If you do not provide this,
            cross validation on the training set will be used. 

        y_val : np.array of shape (n0,) or (n0, 1)
            The validation labels to optimize paramters with. If you do not provide this,
            cross validation on the training set will be used.

        verbose : bool
            Print out useful information when running.'''
        
        validation_data_exists = X_val is not None and y_val is not None
        if validation_data_exists:
            # Duplicate data for each job (expensive)
            job_params = {
                "model": self.model,
                "X_train": X_train,
                "y_train": y_train,
                "X_val": X_val,
                "y_val": y_val,
            }
            params = list(ParameterGrid(param_grid))
            jobs = list(zip([job_params]*len(params), params))
            if verbose:
                print("Comparing", len(jobs), "parameter setting(s) using", self.num_threads, "CPU thread(s)", end=' ')
                print("(", max(1, len(jobs) // self.num_threads), "job(s) per thread ).")
            results = _parallel_param_opt(jobs, threads = self.num_threads)
            results = [result for result in results if result is not None]
            models, scores = list(zip(*results))
            self.model = models[np.argmax(scores)]
        else:
            model_cv = GridSearchCV(
                estimator = self.model, 
                param_grid = param_grid, 
                cv = self.cv_folds, 
                n_jobs = self.num_threads,
                return_train_score = False,
            )
            model_cv.fit(X_train, y_train)
            scores = model_cv.cv_results_['mean_test_score']
            params = model_cv.cv_results_['params']
            self.model = model_cv.best_estimator_
            
        best_score_ranking_idx = np.argsort(scores)[::-1]
        self.scores = [scores[z] for z in best_score_ranking_idx]
        self.params = [params[z] for z in best_score_ranking_idx]
        self.param_scores = list(zip(self.params, self.scores))
        self.best_score = self.scores[0]
        self.best_params = self.params[0]
        return self.model
    
    
    def predict(self, X):
        '''Returns a binary vector of predictions.

        Parameters
        ----------
        X : np.array of shape (n, m)
          The test data as a feature matrix.'''

        return self.model.predict(X)
  
  
    def predict_proba(self, X):
        '''Returns a vector of probabilties P(y=k)
        for each example in X.

        Parameters
        ----------
        X : np.array of shape (n, m)
          The test data as a feature matrix.'''

        return self.model.predict_proba(X)
    
    def score(self, X, y, sample_weight=None):
        '''Returns the model's score on a test set X with labels y.

        Parameters
        ----------
        X : np.array of shape (n, m)
          The test data as a feature matrix.
          
        y : np.array<int> of shape (n,) or (n, 1)
          The test classification labels as an array.
          
        sample_weight : np.array<float> of shape (n,) or (n, 1)
          Weights each example when computing the score / accuracy.'''
        
        if hasattr(self.model, 'score'):
        
            # Check if sample_weight in clf.score(). Compatible with Python 2/3.
            if hasattr(inspect, 'getfullargspec') and                 'sample_weight' in inspect.getfullargspec(self.model.score).args or                 hasattr(inspect, 'getargspec') and                 'sample_weight' in inspect.getargspec(self.model.score).args:  
                return self.model.score(X, y, sample_weight=sample_weight)
            else:
                return self.model.score(X, y)
        else:
            return accuracy_score(y, self.model.predict(X_val), sample_weight=sample_weight) 
        
    
    def get_param_scores(self):
        '''Accessor to return param_scores, a list of tuples
        containing pairs of parameters and the associated score
        on the validation set, ordered by descending score.
        e.g. [({'a':1}, 0.95), ({'a':2}, 0.93), ({'a':0}, 0.87)]'''
        return self.param_scores


    def get_best_params(self):
        '''Accessor to return best_params, a dictionary of the
        parameters that scored the best on the validation set.'''
        return self.best_params


    def get_best_score(self):
        '''Accessor to return best_score, the highest score on the val set.'''
        return self.best_score


    def get_params(self):
        '''Accessor to return params, a list of parameter dicts,
        ordered by descending score on the validation set.'''
        return self.params


    def get_scores(self):
        '''Accessor to return scores, a list of scores ordered
        by descending score on the validation set.'''
        return self.scores

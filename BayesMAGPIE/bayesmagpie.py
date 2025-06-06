# Commented out IPython magic to ensure Python compatibility.
import os
from collections import defaultdict
import torch
import numpy as np
from torch.distributions import constraints
import pandas as pd
import re

import pyro
import pyro.distributions as dist
from pyro import poutine
from pyro.infer.autoguide import AutoDelta
from pyro.optim import Adam
from pyro.infer import SVI, TraceEnum_ELBO, config_enumerate, infer_discrete
from pyro.infer.mcmc import NUTS
smoke_test = "CI" in os.environ

# Set up CPU as the default device
device = torch.device('cpu')

torch.set_default_dtype(torch.float64)

def df_to_tensor(df):
    return torch.from_numpy(df.values).double().to(device)

def cleanData(mutation_df, tmb_df):
    mutation_df = mutation_df.sort_index(axis=1)
    mutation_df = mutation_df.loc[:, mutation_df.sum() != 0]
    mat_x = df_to_tensor(mutation_df) # convert data matrix df to tensor

    col_names = [string[:string.find('_')] if '_' in string else string for string in mutation_df.columns]
    uniq_genes, cts = np.unique(col_names, return_counts=True)

    tmb_vec = df_to_tensor(tmb_df)
    tmb_vec = tmb_vec - tmb_vec.mean()

    nCols = mat_x.size(1)
    return mat_x, tmb_vec, list(mutation_df.columns), uniq_genes, cts, nCols

def createHelpMats(cts, nCols):
    numvariants_ls = list(cts)

    temp1_block_ls = []
    for numvar in numvariants_ls:
        temp1_block_ls.append(torch.ones(numvar, numvar))
    designMat_pas = torch.cat((1- torch.block_diag(*temp1_block_ls), torch.ones(1, nCols)), dim=0)

    comut_indices = torch.nonzero((1-designMat_pas).tril(diagonal=-1) + (1-designMat_pas).triu(diagonal=1))
    num_Comut = comut_indices.size(0)

    designMat_dri = torch.zeros(designMat_pas.size())
    designMat_dri[range(nCols), range(nCols)] = 20.

    designMat_codri = torch.zeros(designMat_pas.size())
    designMat_codri[comut_indices[:,0], comut_indices[:,1]]=1.

    tran_mat = torch.zeros(nCols+1, num_Comut)
    tran_mat[comut_indices[:,0], range(num_Comut)] = 1
    return designMat_pas, designMat_dri, designMat_codri, tran_mat, num_Comut

class output_BayesMAGPIE:
    def __init__(self, driver_freq_feaure_mat, driver_freq_gene_mat, postP_feature, postP_gene):
        self.driver_freq_feature = driver_freq_feaure_mat
        self.driver_freq_gene = driver_freq_gene_mat
        self.prob_mat_feature = postP_feature
        self.prob_mat_gene = postP_gene

def BayesMAGPIE(mutation_df, tmb_df, alpha = .1, nIter = 3000, nInit = 1000, initial_lr = 0.01, gamma = 0.1, rand_seed=2025):
    torch.manual_seed(rand_seed)
    np.random.seed(rand_seed)
    
    lrd = gamma ** (1 / nIter)
    optim = pyro.optim.ClippedAdam({'lr': initial_lr, 'lrd': lrd})
    elbo = TraceEnum_ELBO(max_plate_nesting=1)

    # Re-organize data
    print('Reshaping Input Data...')
    mat_x, tmb_vec, feature_names, uniq_genes, cts, nCols = cleanData(mutation_df, tmb_df)
    print('# of tumors:', mat_x.size(0), '; # of featurs:', nCols, '(including', len(uniq_genes), 'genes)')

    # Set up helper matrices for running algorithm
    designMat_pas, designMat_dri, designMat_codri, tran_mat, num_Comut = createHelpMats(cts, nCols)
    b0_gene_log = (mat_x.mean(0)/(1-mat_x.mean(0))).log()
    b0_mean = b0_gene_log.mean()
    
    @config_enumerate
    def model(data, TMB, alpha):
        alpha_vec = torch.ones(nCols+1) * alpha
        weights = pyro.sample("weights", dist.Dirichlet(alpha_vec))

        comut = pyro.sample("comut", dist.Beta(1., 10.).expand([num_Comut]).to_event(1)).logit()
        b0 = pyro.sample('b0', dist.Normal(b0_mean, 10.).expand([nCols]).to_event(1))
        b1 = pyro.sample('b1', dist.Normal(0.,2.).expand([nCols]).to_event(1))

        # Compute mutation rate
        temp_logit = b0 + TMB * b1
        driProbMat = (tran_mat @ comut)[:,None] * designMat_codri + designMat_dri

        with pyro.plate("data", len(data)):
            assignment = pyro.sample("assignment", dist.Categorical(weights))

            binom_new = dist.Independent(dist.Bernoulli(logits = temp_logit * designMat_pas[assignment] + driProbMat[assignment]), 1)
            pyro.sample("obs", binom_new, obs=data)

    @config_enumerate
    def model_novar(data, TMB, alpha):
        alpha_vec = torch.ones(nCols+1) * alpha
        weights = pyro.sample("weights", dist.Dirichlet(alpha_vec))

        b0 = pyro.sample('b0', dist.Normal(b0_mean, 10.).expand([nCols]).to_event(1))
        b1 = pyro.sample('b1', dist.Normal(0.,2.).expand([nCols]).to_event(1))

        # Compute mutation rate
        temp_logit = b0 + TMB * b1

        with pyro.plate("data", len(data)):
            assignment = pyro.sample("assignment", dist.Categorical(weights))
            binom_new = dist.Independent(dist.Bernoulli(logits = temp_logit * designMat_pas[assignment] + designMat_dri[assignment]), 1)
            pyro.sample("obs", binom_new, obs=data)
           
    if num_Comut>0:
        def init_loc_fn(site):
            if site["name"] == "weights":
                return torch.ones(nCols+1) / (nCols+1)
            if site["name"] == "comut":
                return torch.ones(num_Comut)*.1
            if site["name"] == "b0":
                flip_ind = (torch.randn(nCols)>0).float()
                return b0_gene_log * flip_ind - 6.*(1-flip_ind)
            if site["name"] == "b1":
                return torch.randn(nCols) + 1.
            raise ValueError(site["name"])

        def initialize(seed):
            pyro.set_rng_seed(seed)
            pyro.clear_param_store()
            global_guide = AutoDelta(
                poutine.block(model, expose=["weights", "comut", "b0", "b1"]),
                init_loc_fn=init_loc_fn,
            )
            svi = SVI(model, global_guide, optim, loss=elbo)
            loss = svi.loss(model, global_guide, mat_x, tmb_vec, alpha)
            return loss, svi, global_guide, seed
    else:
        def init_loc_fn(site):
            if site["name"] == "weights":
                return torch.ones(nCols+1) / (nCols+1)
            if site["name"] == "b0":
                flip_ind = (torch.randn(nCols)>0).float()
                return b0_gene_log * flip_ind - 6.*(1-flip_ind)
            if site["name"] == "b1":
                return torch.randn(nCols) + 1.
            raise ValueError(site["name"])

        def initialize(seed):
            pyro.set_rng_seed(seed)
            pyro.clear_param_store()
            global_guide = AutoDelta(
                poutine.block(model_novar, expose=["weights", "b0", "b1"]),
                init_loc_fn=init_loc_fn,
            )
            svi = SVI(model_novar, global_guide, optim, loss=elbo)
            loss = svi.loss(model_novar, global_guide, mat_x, tmb_vec, alpha)
            return loss, svi, global_guide, seed

    # Choose the best among 1000 random initializations.
    print('Running Random Initializations...')
    loss, svi, global_guide, seed = min((initialize(seed) for seed in range(nInit)), key=lambda x: x[0])

    # Run
    print('Running BayesMAGPIE...')
    stop_int = 50

    # Register hooks to monitor gradient norms.
    gradient_norms = defaultdict(list)
    for name, value in pyro.get_param_store().named_parameters():
        value.register_hook(
            lambda g, name=name: gradient_norms[name].append(g.norm().item())
        )

    losses = []
    for i in range(nIter):
        loss = svi.step(mat_x, tmb_vec, alpha)
        losses.append(loss)

        if i >= 100:  # Ensure there are enough previous iterations to compare ### and i % 50 == 0
            grad_norm_vec = gradient_norms["AutoDelta.weights"]
            if abs((grad_norm_vec[-1] - grad_norm_vec[-stop_int]) / grad_norm_vec[-stop_int]) < 1e-6:
                print(f"Early stopping at iteration {i} : loss reduction below threshold.")
                break

    # Estimated Driver Frequency
    map_estimates = global_guide(mat_x, tmb_vec, alpha)
    wgt_out =  map_estimates["weights"]
    newvar = feature_names
    newvar.append('no_driver')
    driver_freq_mat = pd.DataFrame({'gene': newvar, 'weight': wgt_out.cpu().data.numpy()}, columns=['gene', 'weight'])

    # Get Posterior Probability of Driver Genes for Each Tumor
    @config_enumerate
    def full_guide(data, TMB, alpha):
        # Global variables.
        with poutine.block(
            hide_types=["param"]
        ):
            global_guide(data, TMB, alpha)

        # Local variables.
        with pyro.plate("data", len(data)):
            assignment_probs = pyro.param(
                "assignment_probs",
                torch.ones(len(data), nCols+1) / (nCols+1),
                constraint=constraints.simplex,
            )
            pyro.sample("assignment", dist.Categorical(assignment_probs))

    # Variant-type level postP
    optim2 = pyro.optim.Adam({"lr": 0.2, "betas": [0.8, 0.99]})
    elbo2 = TraceEnum_ELBO(max_plate_nesting=1)

    if num_Comut>0:
        svi = SVI(model, full_guide, optim2, loss=elbo2)
    else:
        svi = SVI(model_novar, full_guide, optim2, loss=elbo2)

    losses = []
    for i in range(200 if not smoke_test else 2):
        loss = svi.step(mat_x, tmb_vec, alpha)
        losses.append(loss)

    assignment_probs = pyro.param("assignment_probs")
    postP_feature = pd.DataFrame(assignment_probs.data.cpu().numpy(),
                                 columns = newvar,
                                 index = mutation_df.index)

    # Gene level postP
    gene0 = list(uniq_genes)[0]
    col_set0 = [col for col in postP_feature.columns if re.search(gene0, col)]
    if len(col_set0) > 1:
        postP_gene = postP_feature[col_set0].sum(1)
    else:
        postP_gene = postP_feature[col_set0]

    for gene_j in list(uniq_genes)[1:len(uniq_genes)]:
        col_set = [col for col in postP_feature.columns if re.search(gene_j, col)]
        if len(col_set)> 1:
            postP_gene = pd.concat([postP_gene, postP_feature[col_set].sum(1)],axis=1)
        else:
            postP_gene = pd.concat([postP_gene, postP_feature[col_set]], axis=1)

    postP_gene = pd.concat([postP_gene, postP_feature['no_driver']], axis=1)
    new_columns = list(uniq_genes)
    new_columns.append('no_driver')
    postP_gene.columns = new_columns
    
    # Compute driver_freq_feaure_mat
    driver_freq_feature_df = postP_feature.mean(axis=0).iloc[:-1]
    mut_freq_feature_df = pd.DataFrame(mat_x.mean(0).cpu(), index = feature_names[:-1])
    driver_freq_feaure_mat = pd.concat([mut_freq_feature_df, driver_freq_feature_df],axis=1)
    driver_freq_feaure_mat.columns = ['Mut.Freq', 'Driver.Freq']
    driver_freq_feaure_mat_sort = driver_freq_feaure_mat.sort_values(by='Driver.Freq', ascending=False)

    # Compute driver_freq_feaure_mat
    driver_freq_gene_mat = postP_gene.mean(axis=0).iloc[:-1].sort_values(ascending=False)
    
    out = output_BayesMAGPIE(driver_freq_feaure_mat_sort, driver_freq_gene_mat, postP_feature, postP_gene)
    print('Finished running.')
    return out

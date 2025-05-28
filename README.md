## BayesMAGPIE

BayesMAGPIE is a statistical method for probabilistically identifying driver mutations within individiual oncogenic pathways under the mutual exclusivity framework. It is a refined version of our previously developed method, [**MAGPIE**](https://www.cell.com/ajhg/fulltext/S0002-9297(23)00441-X), published in *AJHG*. 
<br><br>Leveraging a Bayesian hierarchical modeling approach, BayesMAGPIE introduces two key innovations: (1) incorporation of information on mutation type (e.g., missense vs. truncating) to capture potential functional differences among variants within the same gene; and (2) modeling gene-specific driver frequencies with a Dirichlet prior to effectively control sparsity in the inferred driver set.

A tutorial of BayesMAGPIE on Google Colab: <a 
				       href="https://colab.research.google.com/drive/1ozZQ5wAZfWK3i8cazJ003nfelLR7EMzw?usp=sharing">
  	<img src="https://colab.research.google.com/assets/colab-badge.svg" alt="Open In Colab"/>
	</a>
	

## Installation

Method 1: Install directly via `pip`
<pre> pip install git+https://github.com/MSK-WANGX/BayesMAGPIE.git </pre>

Method 2: Clone the repo and install locally
<pre> git clone https://github.com/MSK-WANGX/BayesMAGPIE.git <br> cd BayesMAGPIE <br> pip install . </pre>


## Core function: Inferring Driver Frequencies and Posterior Probability Matrix

<pre> BayesMAGPIE(mutation_df, tmb_df, alpha=0.1, nIter=3000, nInit=1000, initial_lr=0.01, gamma=0.1, rand_seed=2025)</pre>

### Inputs
**Required:**
- `mutation_df`: A binary gene alteration matrix (*pandas.DataFrame* of shape *n* by *m*, *n*: # of tumors; *m*: # of features). Each feature represents either a gene (e.g., *EGFR*) or a specific mutation type within a gene (e.g., *EGFR_missense* or *EGFR_other*). **Do not** include both a general gene and its mutation subtypes simultaneously, e.g., avoid including *EGFR* along with *EGFR_missense* and *EGFR_other*), in the dataset. See the tutorial and example dataset for input preparation guidance.
- `tmb_df`: Tumor mutational burden score for each tumor (*pandas.DataFrame* of length *n*). This can be binary or continuous. For continuous values, we recommend applying a log-transformation to raw mutation counts followed by centering the data.

**Optional:**
- `alpha` (float): Dirichlet concentration parameter (default = 0.1). Smaller values (e.g., 0.1) encourage sparsity in the inferred driver set, which generally reduces both false positive rate (FPR) and true positive rate (TPR). Larger values (e.g., >1) increase FPR and are not recommended.
- `nIter` (int): Number of iterations for the Adam optimizer (default = 3000). Early stopping is applied if the loss does not decrease much.
- `nInit` (int): Number of random initializations to evaluate (default = 1000).
- `initial_lr` (float): Initial learning rate for the Adam optimizer (default = 0.01). The learning rate decays during training.
- `gamma` (float): Final-to-initial learning rate ratio (default = 0.1), resulting in decay from 0.01 to 0.001 over the course of training.
- `rand_seed` (int): Random seed for reproducibility.

### Outputs
- `driver_freq_feaure_mat`: A *pandas.DataFrame* with two columns. The first column shows the observed relative mutation frequency for each feature (gene or gene-specific mutation type), and the second column reports the inferred driver frequency estimated by BayesMAGPIE.
- `driver_freq_gene_mat` Similar to `driver_freq_feaure_mat`, but driver frequencies are summarized at the gene level.
- `postP_feature`: A *pandas.DataFrame* of shape *n* × (*m* + 1). Each row corresponds to a tumor and each column (except the last) represents the posterior probability of a driver mutation in a specific feature. The final column contains the posterior probability that no driver mutation is present.
- `postP_gene`: Similar to `postP_feature`, but with posterior probabilities summarized at the gene level. Each column corresponds to a gene.

## Paper
Wang X, Kostrzewa C, Reiner A, Shen R, Colin B. A Bayesian Approach for Identifying Driver Mutations within Oncogenic Pathways through Mutual Exclusivity. *Submitted* (2025+).

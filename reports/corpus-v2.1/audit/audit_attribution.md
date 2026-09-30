| # | entry | verdict | first error | registered | audit label | evidence / rationale |
|--|--|--|--|--|--|--|
| 1 | nadiinchi__power_laws_deep_ensembles | BLOCKED | ModuleNotFoundError: No module named 'tabulate' | REPO | REPO_UNDECLARED | 'tabulate' (as tabulate) is declared in no manifest, Dockerfile, or install line |
| 2 | DeformableFriends__NeuralTracking | BLOCKED | start_nnrt.sh: 27: docker: not found | REPO | PLATFORM_REQUIRED | the command needs a GPU / Docker the sandbox does not provide |
| 3 | autumn9999__vmtl | BLOCKED | ModuleNotFoundError: No module named 'sklearn' | REPO | REPO_UNDECLARED | 'sklearn' (as scikit-learn, sklearn) is declared in no manifest, Dockerfile, or install line |
| 4 | damo-cv__img-comp-reference | BLOCKED | Exception: No GPU found, please run without --cuda | REPO | PLATFORM_REQUIRED | the command needs a GPU / Docker the sandbox does not provide |
| 5 | BorgwardtLab__topological-autoencoders | INDETERMINATE | ERROR: ResolutionImpossible: for help visit https://pip.pypa.io/en/lat | - | ENV_ROT | the runner's torch install could not resolve the repo's historical pins on this Python |
| 6 | grigorisg9gr__rocgan | BLOCKED | ModuleNotFoundError: No module named 'chainer' | REPO | REPO_UNDECLARED | 'chainer' (as chainer) is declared in no manifest, Dockerfile, or install line; the README mentions it in prose (4 line(s)) |
| 7 | albertometelli__pfqi | BLOCKED | ModuleNotFoundError: No module named 'numpy' | REPO | REPO_UNDECLARED | 'numpy' (as numpy) is declared in no manifest, Dockerfile, or install line; the README mentions it in prose (1 line(s)) |
| 8 | edenton__svg | BLOCKED | ModuleNotFoundError: No module named 'sklearn' | REPO | REPO_UNDECLARED | 'sklearn' (as scikit-learn, sklearn) is declared in no manifest, Dockerfile, or install line |
| 9 | omarfoq__fedem | INDETERMINATE | ERROR: Could not find a version that satisfies the requirement torch== | - | ENV_ROT | the runner's torch install could not resolve the repo's historical pins on this Python |
| 10 | alevine0__patchSmoothing | BLOCKED | ModuleNotFoundError: No module named 'scipy' | REPO | REPO_UNDECLARED | 'scipy' (as scipy) is declared in no manifest, Dockerfile, or install line |
| 11 | JindongGu__VoteAttack | BLOCKED | ModuleNotFoundError: No module named 'tqdm' | REPO | REPO_UNDECLARED | 'tqdm' (as tqdm) is declared in no manifest, Dockerfile, or install line |
| 12 | Mehran-k__SimplE | BLOCKED | ModuleNotFoundError: No module named 'tensorflow' | REPO | REPO_UNDECLARED | 'tensorflow' (as tensorflow, tensorflow-cpu, tensorflow-gpu) is declared in no manifest, Dockerfile, or install line; the README mentions it in prose (1 line(s)) |
| 13 | seongjunyun__neo_gnns | BLOCKED | ModuleNotFoundError: No module named 'torch_sparse' | REPO | REPO_UNDECLARED | 'torch_sparse' (as torch-sparse) is declared in no manifest, Dockerfile, or install line |
| 14 | IST-DASLab__M-FAC | BLOCKED | AttributeError: module 'torch._C' has no attribute '_cuda_setDevice' | REPO | PLATFORM_REQUIRED | the command needs a GPU / Docker the sandbox does not provide |
| 15 | YuliaRubanova__latent_ode | BLOCKED | ModuleNotFoundError: No module named 'matplotlib' | REPO | REPO_UNDECLARED | 'matplotlib' (as matplotlib) is declared in no manifest, Dockerfile, or install line |
| 16 | bckim92__sequential-knowledge-transformer | BLOCKED | ModuleNotFoundError: No module named 'sklearn' | REPO | REPO_UNDECLARED | 'sklearn' (as scikit-learn, sklearn) is declared in no manifest, Dockerfile, or install line |
| 17 | Haichao-Zhang__FeatureScatter | BLOCKED | ImportError: cannot import name 'zero_gradients' from 'torch.autograd. | REPO | ENV_ROT (judgment) | an API removed from newer torch (the repo pins no torch; the runner installs the newest): unpinned drift |
| 18 | aam-at__adversary_critic | RUNS_CLEAN |  | - | PASS | ran clean |
| 19 | lrjconan__RBP | BLOCKED | ModuleNotFoundError: No module named 'operators._ext' | REPO | REPO_UNDECLARED (judgment) | 'operators._ext' (as operators) is declared in no manifest, Dockerfile, or install line; the README mentions it in prose (1 line(s)); it is the repo's OWN module (a compiled extension / build step), not a package |
| 20 | XiaoxiaoGuo__fashion-retrieval | BLOCKED | ModuleNotFoundError: No module named 'six' | REPO | REPO_UNDECLARED | 'six' (as six) is declared in no manifest, Dockerfile, or install line |

**Gate (>= 8 REPO-attributed non-PASS):** (a) pre-registered rule = **17**; (b) audit (REPO_UNDECLARED only) = **13** (12 if the repo's own compiled module of entry 19 is excluded).
Labels: {'REPO_UNDECLARED': 13, 'PLATFORM_REQUIRED': 3, 'ENV_ROT': 3, 'PASS': 1}

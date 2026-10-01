# ILLUSTRATIVE memory note (not produced by any system)

Built by `scripts/build_example_01.py` with fixed rules from the recorded trajectory of `pytorch__ignite-484` (tenant-3). No memory system produced this text and no agent was given it. It shows what a distilled note *could* contain if it were made only from what that earlier run actually saw. The rules look only at the earlier run, never at the later task: (1) every file/directory inside the repository it opened (files it created itself are left out), with the git object id at its base commit; (2) the class/def outline of every .py file it viewed in full; (3) every directory listing of the repository, as entry names; (4) every test run that printed per-test outcomes: command, summary, and the test ids with outcomes, de-duplicated across runs; (5) edits it made to files it did not create. The token numbers in the README do not depend on this note.

- Source task: `pytorch__ignite-484` (issue: "[Metrics] add indexing synthetic sugar")
- Source base commit: `6b8b16bac9`; recorded run resolved its own task: True

## Files and directories it opened (first view of each)

| Path | What it saw | Object id at source commit |
|---|---|---|
| `.` | directory listing (step 3) | tree 53cc38e328 |
| `README.rst` | whole file (step 4) | blob 62b95a738f |
| `ignite/metrics` | directory listing (step 7) | tree 3ae17e3855 |
| `ignite/metrics/metric.py` | whole file (step 9) | blob 4520d2aa7d |
| `ignite/metrics/metrics_lambda.py` | whole file (step 10) | blob e8cc3ce815 |
| `ignite/metrics/confusion_matrix.py` | whole file (step 11) | blob 4325e3b869 |
| `tests/ignite/metrics/test_confusion_matrix.py` | lines 1-50 (step 15) | blob e8a4f2a881 |
| `tests/ignite/metrics/test_metrics_lambda.py` | lines 1-100 (step 17) | blob 8a5855f1df |

## Listing of `.` (step 3, entry names relative to it)

`CONTRIBUTING.md`, `LICENSE`, `PULL_REQUEST_TEMPLATE.md`, `README.rst`, `assets/`, `assets/ignite_vs_bare_pytorch.png`, `codecov.yml`, `conda.recipe/`, `conda.recipe/conda_build_config.yaml`, `conda.recipe/meta.yaml`, `docs/`, `docs/Makefile`, `docs/make.bat`, `docs/requirements.txt`, `docs/source/`, `examples/`, `examples/contrib/`, `examples/fast_neural_style/`, `examples/gan/`, `examples/mnist/`, `examples/notebooks/`, `examples/reinforcement_learning/`, `ignite/`, `ignite/__init__.py`, `ignite/_six.py`, `ignite/_utils.py`, `ignite/contrib/`, `ignite/engine/`, `ignite/exceptions.py`, `ignite/handlers/`, `ignite/metrics/`, `ignite/utils.py`, `pytorch_ignite.egg-info/`, `pytorch_ignite.egg-info/PKG-INFO`, `pytorch_ignite.egg-info/SOURCES.txt`, `pytorch_ignite.egg-info/dependency_links.txt`, `pytorch_ignite.egg-info/requires.txt`, `pytorch_ignite.egg-info/top_level.txt`, `pytorch_ignite.egg-info/zip-safe`, `setup.cfg`, `setup.py`, `tests/`, `tests/__init__.py`, `tests/ignite/`, `tox.ini`

## Listing of `ignite/metrics` (step 7, entry names relative to it)

`__init__.py`, `accuracy.py`, `confusion_matrix.py`, `epoch_metric.py`, `loss.py`, `mean_absolute_error.py`, `mean_pairwise_distance.py`, `mean_squared_error.py`, `metric.py`, `metrics_lambda.py`, `precision.py`, `recall.py`, `root_mean_squared_error.py`, `running_average.py`, `top_k_categorical_accuracy.py`

## Outline of `ignite/metrics/metric.py` (class/def lines as numbered in its step-9 view)

```
   7  class Metric(with_metaclass(ABCMeta, object)):
  19      def __init__(self, output_transform=lambda x: x):
  24      def reset(self):
  33      def update(self, output):
  45      def compute(self):
  59      def started(self, engine):
  63      def iteration_completed(self, engine):
  67      def completed(self, engine, name):
  73      def attach(self, engine, name):
  80      def __add__(self, other):
  84      def __radd__(self, other):
  88      def __sub__(self, other):
  92      def __rsub__(self, other):
  96      def __mul__(self, other):
 100      def __rmul__(self, other):
 104      def __pow__(self, other):
 108      def __rpow__(self, other):
 112      def __mod__(self, other):
 116      def __div__(self, other):
 120      def __rdiv__(self, other):
 124      def __truediv__(self, other):
 128      def __rtruediv__(self, other):
 132      def __floordiv__(self, other):
 136      def __getattr__(self, attr):
 139          def fn(x, *args, **kwargs):
 142          def wrapper(*args, **kwargs):
```

## Outline of `ignite/metrics/metrics_lambda.py` (class/def lines as numbered in its step-10 view)

```
   6  class MetricsLambda(Metric):
  29          def Fbeta(r, p, beta):
  37      def __init__(self, f, *args, **kwargs):
  43      def reset(self):
  48      def update(self, output):
  54      def compute(self):
  59      def _internal_attach(self, engine):
  69      def attach(self, engine, name):
```

## Outline of `ignite/metrics/confusion_matrix.py` (class/def lines as numbered in its step-11 view)

```
  10  class ConfusionMatrix(Metric):
  32      def __init__(self, num_classes, average=None, output_transform=lambda x: x):
  42      def reset(self):
  46      def _check_shape(self, output):
  73      def update(self, output):
  92      def compute(self):
 105  def IoU(cm, ignore_index=None):
 140          def ignore_index_fn(iou_vector):
 153  def mIoU(cm, ignore_index=None):
 180  def cmAccuracy(cm):
 194  def cmPrecision(cm, average=True):
 212  def cmRecall(cm, average=True):
```

## Test runs with per-test outcomes

- step 35: `python -m pytest tests/ignite/metrics/test_metrics_lambda.py::test_metrics_lambda -v`; result: 1 passed in 1.36s
- step 47: `python -m pytest tests/ignite/metrics/test_metrics_lambda.py -v`; result: 7 passed in 0.68s
- step 48: `python -m pytest tests/ignite/metrics/test_confusion_matrix.py -v`; result: 13 passed in 0.78s
- step 52: `python -m pytest tests/ignite/metrics/test_confusion_matrix.py tests/ignite/metrics/test_metrics_lambda.py tests/ignite/metrics/test_accuracy.py -v`; result: 35 passed in 0.96s; output truncated in the recording, 27 per-test lines visible
- step 61: `python -m pytest tests/ignite/metrics/test_metric.py -v`; result: 8 passed in 0.70s

Test ids seen across these runs (41 unique):

- `tests/ignite/metrics/test_metrics_lambda.py`: `test_metrics_lambda` PASSED, `test_metrics_lambda_reset` PASSED, `test_integration` PASSED, `test_integration_ingredients_not_attached` PASSED, `test_state_metrics` PASSED, `test_state_metrics_ingredients_not_attached` PASSED, `test_recursive_attachment` PASSED
- `tests/ignite/metrics/test_confusion_matrix.py`: `test_no_update` PASSED, `test_multiclass_wrong_inputs` PASSED, `test_multiclass_input_N` PASSED, `test_multiclass_input_NL` PASSED, `test_multiclass_input_NHW` PASSED, `test_multiclass_images` PASSED, `test_iou_wrong_input` PASSED, `test_iou` PASSED, `test_miou` PASSED, `test_cm_accuracy` PASSED, `test_cm_precision` PASSED, `test_cm_recall` PASSED, `test_cm_with_average` PASSED
- `tests/ignite/metrics/test_accuracy.py`: `test_binary_wrong_inputs` PASSED, `test_binary_input_N` PASSED, `test_binary_input_NL` PASSED, `test_binary_input_NHW` PASSED, `test_multiclass_wrong_inputs` PASSED, `test_multiclass_input_N` PASSED, `test_multiclass_input_NL` PASSED, `test_multiclass_input_NHW` PASSED, `test_multilabel_wrong_inputs` PASSED, `test_multilabel_input_N` PASSED, `test_multilabel_input_NL` PASSED, `test_multilabel_input_NHW` PASSED, `test_incorrect_type` PASSED
- `tests/ignite/metrics/test_metric.py`: `test_no_transform` PASSED, `test_transform` PASSED, `test_no_grad` PASSED, `test_arithmetics` PASSED, `test_attach` PASSED, `test_integration` PASSED, `test_abstract_class` PASSED, `test_pytorch_operators` PASSED

## Edits to files it did not create (str_replace / insert)

- step 21: `ignite/metrics/metric.py` (str_replace)

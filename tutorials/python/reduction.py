"""
Reduction
=========
**Author**: `Tianqi Chen <https://tqchen.github.io>`_

This is an introduction material on how to do reduction in TVM.
Associative reduction operators like sum/max/min are typical
construction blocks of linear algebra operations.

In this tutorial, we will demonstrate how to do reduction in TVM.
"""
from __future__ import absolute_import, print_function

import tvm
import numpy as np

######################################################################
# Describe Sum of Rows
# --------------------
# Assume we want to compute sum of rows as our example.
# In numpy semantics this can be written as :code:`B = numpy.sum(A, axis=1)`
#
# The following lines describes the row sum operation.
# To create a reduction formula, we declare a reduction axis using
# :any:`tvm.reduce_axis`. :any:`tvm.reduce_axis` takes in the range of reductions.
# :any:`tvm.sum` takes in the expression to be reduced as well as the reduction
# axis and compute the sum of value over all k in the declared range.
#
# The equivalent C code is as follows:
#
# .. code-block:: c
#
#   for (int i = 0; i < n; ++i) {
#     B[i] = 0;
#     for (int k = 0; k < m; ++k) {
#       B[i] = B[i] + A[i][k];
#     }
#   }
#
n = tvm.var("n")
m = tvm.var("m")
A = tvm.placeholder((n, m), name='A')
k = tvm.reduce_axis((0, m), "k")
B = tvm.compute((n,), lambda i: tvm.sum(A[i, k], axis=k), name="B")

######################################################################
# Schedule the Reduction
# ----------------------
# There are several ways to schedule a reduction.
# Before doing anything, let us print out the IR code of default schedule.
#
s = tvm.create_schedule(B.op)
print(tvm.lower(s, [A, B], simple_mode=True))

######################################################################
# You can find that the IR code is quite like the C code.
# The reduction axis is similar to a normal axis, it can be splitted.
#
# In the following code we split both the row axis of B as well
# axis by different factors. The result is a nested reduction.
#
ko, ki = s[B].split(B.op.reduce_axis[0], factor=16)
xo, xi = s[B].split(B.op.axis[0], factor=32)
print(tvm.lower(s, [A, B], simple_mode=True))

######################################################################
# If we are building a GPU kernel, we can bind the rows of B to GPU threads.
s[B.op].bind(xo, tvm.thread_axis("blockIdx.x"))
s[B.op].bind(xi, tvm.thread_axis("threadIdx.x"))
print(tvm.lower(s, [A, B], simple_mode=True))

######################################################################
# Reduction Factoring and Parallelization
# ---------------------------------------
# One problem of building a reduction is that we cannot simply
# parallelize over the reduction axis. We need to devide the computation
# of the reduction, store the local reduction result in a temporal array.
# Before doing a reduction over the temp array.
#
# The rfactor primitive does such rewrite of the computation.
# In the following schedule, the result of B is write written to a temporary
# result B.rf. The factored dimension becomes the first dimension of B.rf.
#
s = tvm.create_schedule(B.op)
ko, ki = s[B].split(B.op.reduce_axis[0], factor=16)
BF = s.rfactor(B, ki)
print(tvm.lower(s, [A, B], simple_mode=True))

######################################################################
# The scheduled operator of B also get rewritten to be sum over
# the first axis of reduced result of B.f
#
print(s[B].op.body)

######################################################################
# Cross Thread Reduction
# ----------------------
# We can now parallelize over the factored axis.
# Here mark the reduction axis of B is marked to be a thread.
# tvm allow reduction axis to be marked as thread if it is the only
# axis in reduction and cross thread reduction is possible in the device.
#
# This is indeed the case after the factoring.
# We can directly compute BF at the reduction axis as well.
# The final generated kernel will divides the rows by blockIdx.x and threadIdx.y
# columns by threadIdx.x and finally do a cross thread reduction over threadIdx.x
#
xo, xi = s[B].split(s[B].op.axis[0], factor=32)
s[B.op].bind(xo, tvm.thread_axis("blockIdx.x"))
s[B.op].bind(xi, tvm.thread_axis("threadIdx.y"))
s[B].bind(s[B].op.reduce_axis[0], tvm.thread_axis("threadIdx.x"))
s[BF].compute_at(s[B], s[B].op.reduce_axis[0])
fcuda = tvm.build(s, [A, B], "cuda")
print(fcuda.imported_modules[0].get_source())

######################################################################
# Verify the correctness of result kernel by comparing it to numpy.
#
nn = 128
ctx  = tvm.gpu(0)
a = tvm.nd.array(np.random.uniform(size=(nn, nn)).astype(A.dtype), ctx)
b = tvm.nd.array(np.zeros(nn, dtype=B.dtype), ctx)
fcuda(a, b)
np.testing.assert_allclose(
    b.asnumpy(),  np.sum(a.asnumpy(), axis=1), rtol=1e-4)

######################################################################
# Define General Commutative Reduction Operation
# ----------------------------------------------
# Besides the built-in reduction operations like :any:`tvm.sum`,
# :any:`tvm.min` and :any:`tvm.max`, you can also define your
# commutative reduction operation by :any:`tvm.comm_reducer`.
#

n = tvm.var('n')
m = tvm.var('m')
product = tvm.comm_reducer(lambda x, y: x*y,
    lambda t: tvm.const(1, dtype=t), name="product")
A = tvm.placeholder((n, m), name='A')
k = tvm.reduce_axis((0, m), name='k')
B = tvm.compute((n,), lambda i: product(A[i, k], axis=k), name='B')


######################################################################
# Summary
# -------
# This tutorial provides a walk through of reduction schedule.
#
# - Describe reduction with reduce_axis.
# - Use rfactor to factor out axis if we need parallelism.
# - Define new reduction operation by :any:`tvm.comm_reducer`

# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
# pylint: disable=redefined-builtin
"""Operators to implement operaor gradients. Used in `_op_gradient.py`.

We are trying to keep grad operators as simple as possible, and hope they are only used for finding
gradients for forward operators. The struct_info inference for grad operators just returns the
struct_info of the input.
"""
from typing import Optional, Tuple

from . import _ffi_api
from ...expr import Expr


def no_grad(input: Expr) -> Expr:
    """No gradient dummy operator w.r.t. the input.

    Parameters
    ----------
    input : relax.Expr
      The corresponding input tensor.

    Returns
    -------
    result : relax.Expr
      The no-gradient representation w.r.t. input.
    """
    return _ffi_api.no_grad(input)  # type: ignore


def nll_loss_backward(
    output_grad: Expr,
    predictions: Expr,
    targets: Expr,
    weights: Optional[Expr] = None,
    reduction: str = "mean",
    ignore_index: int = -100,
) -> Expr:
    """Backward operator of relax.nll_loss. All parameters except output_grad is the same as
    relax.nll_loss. Returns the gradient w.r.t. predictions.

    Parameters
    ----------
    output_grad : relax.Expr
      The gradient w.r.t. the result of nll_loss.

    Returns
    -------
    result : relax.Expr
      The gradient w.r.t. predictions.
    """
    return _ffi_api.nll_loss_backward(  # type: ignore
        output_grad, predictions, targets, weights, reduction, ignore_index
    )


def max_pool2d_backward(
    output_grad: Expr,
    data: Expr,
    pool_size: Tuple[int, int] = (1, 1),
    strides: Tuple[int, int] = (1, 1),
    padding: Tuple[int, int, int, int] = (0, 0, 0, 0),
    dilation: Tuple[int, int] = (1, 1),
    ceil_mode: bool = False,
    layout: str = "NCHW",
    out_layout: Optional[str] = None,
) -> Expr:
    """Backward operator of relax.max_pool2d. All parameters except output_grad is the same as
    relax.max_pool2d. Returns the gradient w.r.t. data.

    Parameters
    ----------
    output_grad : relax.Expr
      The gradient w.r.t. the result of max_pool2d.

    Returns
    -------
    result : relax.Expr
      The gradient w.r.t. data.
    """
    return _ffi_api.max_pool2d_backward(  # type: ignore
        output_grad, data, pool_size, strides, padding, dilation, ceil_mode, layout, out_layout
    )


def avg_pool2d_backward(
    output_grad: Expr,
    data: Expr,
    pool_size: Tuple[int, int] = (1, 1),
    strides: Tuple[int, int] = (1, 1),
    padding: Tuple[int, int, int, int] = (0, 0, 0, 0),
    dilation: Tuple[int, int] = (1, 1),
    ceil_mode: bool = False,
    layout: str = "NCHW",
    out_layout: Optional[str] = None,
) -> Expr:
    """Backward operator of relax.avg_pool2d. All parameters except output_grad is the same as
    relax.avg_pool2d. Returns the gradient w.r.t. data.

    Parameters
    ----------
    output_grad : relax.Expr
      The gradient w.r.t. the result of avg_pool2d.

    Returns
    -------
    result : relax.Expr
      The gradient w.r.t. data.
    """
    return _ffi_api.avg_pool2d_backward(  # type: ignore
        output_grad, data, pool_size, strides, padding, dilation, ceil_mode, layout, out_layout
    )


def take_backward(output_grad: Expr, x: Expr, indices: Expr, axis: Optional[int] = None) -> Expr:
    """Backward operator of relax.take. All parameters except output_grad is the same as
    relax.take. Returns the gradient w.r.t. x.

    Parameters
    ----------
    output_grad : relax.Expr
      The gradient w.r.t. the result of take.

    Returns
    -------
    result : relax.Expr
      The gradient w.r.t. x.
    """
    return _ffi_api.take_backward(output_grad, x, indices, axis)  # type: ignore

/*
 * Licensed to the Apache Software Foundation (ASF) under one
 * or more contributor license agreements.  See the NOTICE file
 * distributed with this work for additional information
 * regarding copyright ownership.  The ASF licenses this file
 * to you under the Apache License, Version 2.0 (the
 * "License"); you may not use this file except in compliance
 * with the License.  You may obtain a copy of the License at
 *
 *   http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing,
 * software distributed under the License is distributed on an
 * "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
 * KIND, either express or implied.  See the License for the
 * specific language governing permissions and limitations
 * under the License.
 */

/*!
 * \file src/relax/op/nn/convolution.cc
 * \brief Convolution operators
 */

#include "convolution.h"

#include <vector>

namespace tvm {
namespace relax {

/* relax.nn.conv2d */
TVM_REGISTER_NODE_TYPE(Conv2DAttrs);

Expr conv2d(Expr data, Expr weight, Array<IntImm> strides, Array<IntImm> padding,
            Array<IntImm> dilation, int groups, String data_layout, String kernel_layout,
            Optional<String> out_layout, DataType out_dtype) {
  padding = GetCompletePadding2D(std::move(padding));
  if (strides.size() == 1) {
    strides.push_back(strides[0]);
  }
  if (dilation.size() == 1) {
    dilation.push_back(dilation[0]);
  }

  CHECK_GT(groups, 0) << "The number of groups in convolution is expected to be positive. However, "
                         "the given number of groups is "
                      << groups;
  CHECK_EQ(strides.size(), 2)
      << "The input strides length is expected to be 2. However, the given strides is " << strides;
  CHECK_EQ(dilation.size(), 2)
      << "The input dilation length is expected to be 2. However, the given dilation is "
      << dilation;
  return MakeConv<Conv2DAttrs>(std::move(data), std::move(weight), std::move(strides),
                               std::move(padding), std::move(dilation), groups, data_layout,
                               std::move(kernel_layout), out_layout.value_or(data_layout),
                               out_dtype, /*op_name=*/"relax.nn.conv2d");
}

TVM_REGISTER_GLOBAL("relax.op.nn.conv2d").set_body_typed(conv2d);

StructInfo InferStructInfoConv2d(const Call& call, const BlockBuilder& ctx) {
  Array<TensorStructInfo> input_sinfo = GetInputTensorStructInfo(call, ctx);
  TensorStructInfo data_sinfo = input_sinfo[0];
  TensorStructInfo weight_sinfo = input_sinfo[1];

  const auto* attrs = call->attrs.as<Conv2DAttrs>();
  auto [data_layout, data2NCHW] = CheckTensorLayout(call, ctx, attrs->data_layout,  //
                                                    /*tgt_layout=*/"NCHW",          //
                                                    /*tensor_name=*/"data");
  auto [weight_layout, weight2OIHW] = CheckTensorLayout(call, ctx, attrs->kernel_layout,  //
                                                        /*tgt_layout=*/"OIHW",            //
                                                        /*tensor_name=*/"kernel");
  auto [out_layout, out2NCHW] = CheckTensorLayout(call, ctx, attrs->out_layout,  //
                                                  /*tgt_layout=*/"NCHW",         //
                                                  /*tensor_name=*/"output");

  Optional<ShapeExpr> data_shape =
      CheckNdimPerLayoutAndGetShape(call, ctx, data_sinfo, data_layout);
  Optional<ShapeExpr> weight_shape =
      CheckNdimPerLayoutAndGetShape(call, ctx, weight_sinfo, weight_layout);

  DataType out_dtype = attrs->out_dtype.is_void()
                           ? InferBinaryArithOpOutDtype(call, ctx, data_sinfo, weight_sinfo)
                           : attrs->out_dtype;
  if (!data_shape.defined() || !weight_shape.defined()) {
    return TensorStructInfo(out_dtype, out_layout.ndim());
  }

  Array<PrimExpr> data_NCHW_shape = data2NCHW.ForwardShape(data_shape.value()->values);
  Array<PrimExpr> weight_OIHW_shape = weight2OIHW.ForwardShape(weight_shape.value()->values);

  arith::Analyzer* analyzer = ctx->GetAnalyzer();
  PrimExpr input_channel_data = data_NCHW_shape[1];
  PrimExpr input_channel_kernel = weight_OIHW_shape[1];
  if (analyzer->CanProve(input_channel_data != input_channel_kernel * attrs->groups)) {
    ctx->ReportFatal(
        Diagnostic::Error(call)
        << "The channel size of the data should equal to the product of input channel size of the "
           "weight and the number of groups. However, the data channel size is "
        << input_channel_data << " while the weight input channel size and number of groups are "
        << input_channel_kernel << " and " << attrs->groups);
  } else if (!analyzer->CanProveEqual(input_channel_data, input_channel_kernel * attrs->groups)) {
    // Todo(relax-team): Trust the input shape at this moment, and revisit
    // this condition with runtime shape check
  }
  if (analyzer->CanProve(floormod(weight_OIHW_shape[0], attrs->groups) != 0)) {
    ctx->ReportFatal(Diagnostic::Error(call)
                     << "Conv2d expects the number of output channels to be divisible by the "
                        "number of groups. However, the number of output channels is "
                     << weight_OIHW_shape[0] << " while the number of groups is " << attrs->groups);
  } else if (!analyzer->CanProveEqual(floormod(weight_OIHW_shape[0], attrs->groups), 0)) {
    // Todo(relax-team): Trust the input shape at this moment, and revisit
    // this condition with runtime shape check
  }

  PrimExpr input_h = data_NCHW_shape[2];
  PrimExpr input_w = data_NCHW_shape[3];
  PrimExpr kernel_h = weight_OIHW_shape[2];
  PrimExpr kernel_w = weight_OIHW_shape[3];
  PrimExpr padding_h = attrs->padding[0] + attrs->padding[2];
  PrimExpr padding_w = attrs->padding[1] + attrs->padding[3];

  std::vector<PrimExpr> out_NCHW_shape;
  out_NCHW_shape.resize(4);
  out_NCHW_shape[0] = data_NCHW_shape[0];
  out_NCHW_shape[1] = weight_OIHW_shape[0];

  PrimExpr numerator_h = input_h + padding_h - attrs->dilation[0] * (kernel_h - 1) - 1;
  PrimExpr numerator_w = input_w + padding_w - attrs->dilation[1] * (kernel_w - 1) - 1;
  out_NCHW_shape[2] = analyzer->Simplify(floordiv(numerator_h, attrs->strides[0]) + 1);
  out_NCHW_shape[3] = analyzer->Simplify(floordiv(numerator_w, attrs->strides[1]) + 1);

  Array<PrimExpr> out_shape = out2NCHW.BackwardShape(out_NCHW_shape);
  return TensorStructInfo(ShapeExpr(out_shape), out_dtype);
}

TVM_REGISTER_OP("relax.nn.conv2d")
    .set_num_inputs(2)
    .add_argument("data", "Tensor", "The input tensor.")
    .add_argument("weight", "Tensor", "The weight tensor.")
    .set_attrs_type<Conv2DAttrs>()
    .set_attr<FInferStructInfo>("FInferStructInfo", InferStructInfoConv2d);

/* relax.nn.conv2d_transpose */
TVM_REGISTER_NODE_TYPE(Conv2DTransposeAttrs);

Expr conv2d_transpose(Expr data, Expr weight, Array<IntImm> strides, Array<IntImm> padding,
                      Array<IntImm> output_padding, Array<IntImm> dilation, int groups,
                      String data_layout, String kernel_layout, Optional<String> out_layout,
                      DataType out_dtype) {
  padding = GetCompletePadding2D(std::move(padding));
  if (output_padding.size() == 1) {
    output_padding.push_back(output_padding[0]);
  }
  if (strides.size() == 1) {
    strides.push_back(strides[0]);
  }
  if (dilation.size() == 1) {
    dilation.push_back(dilation[0]);
  }

  CHECK_GT(groups, 0) << "The number of groups in convolution is expected to be positive. However, "
                         "the given number of groups is "
                      << groups;
  CHECK_EQ(output_padding.size(), 2) << "The input output_padding length is expected to be 4. "
                                        "However, the given output_padding is "
                                     << output_padding;
  CHECK_EQ(strides.size(), 2)
      << "The input strides length is expected to be 2. However, the given strides is " << strides;
  CHECK_EQ(dilation.size(), 2)
      << "The input dilation length is expected to be 2. However, the given dilation is "
      << dilation;

  auto attrs = make_object<Conv2DTransposeAttrs>();
  attrs->strides = ConvertIntImmToInt64(strides);
  attrs->padding = ConvertIntImmToInt64(padding);
  attrs->output_padding = ConvertIntImmToInt64(output_padding);
  attrs->dilation = ConvertIntImmToInt64(dilation);
  attrs->groups = groups;
  attrs->data_layout = data_layout;
  attrs->kernel_layout = std::move(kernel_layout);
  attrs->out_layout = std::move(out_layout.value_or(data_layout));
  attrs->out_dtype = std::move(out_dtype);
  const Op& op = Op::Get("relax.nn.conv2d_transpose");
  return Call(op, {data, weight}, Attrs(attrs), {});
}

TVM_REGISTER_GLOBAL("relax.op.nn.conv2d_transpose").set_body_typed(conv2d_transpose);

StructInfo InferStructInfoConv2dTranspose(const Call& call, const BlockBuilder& ctx) {
  Array<TensorStructInfo> input_sinfo = GetInputTensorStructInfo(call, ctx);
  TensorStructInfo data_sinfo = input_sinfo[0];
  TensorStructInfo weight_sinfo = input_sinfo[1];

  const auto* attrs = call->attrs.as<Conv2DTransposeAttrs>();
  auto [data_layout, data2NCHW] = CheckTensorLayout(call, ctx, attrs->data_layout,  //
                                                    /*tgt_layout=*/"NCHW",          //
                                                    /*tensor_name=*/"data");
  auto [weight_layout, weight2IOHW] = CheckTensorLayout(call, ctx, attrs->kernel_layout,  //
                                                        /*tgt_layout=*/"IOHW",            //
                                                        /*tensor_name=*/"kernel");
  auto [out_layout, out2NCHW] = CheckTensorLayout(call, ctx, attrs->out_layout,  //
                                                  /*tgt_layout=*/"NCHW",         //
                                                  /*tensor_name=*/"output");

  Optional<ShapeExpr> data_shape =
      CheckNdimPerLayoutAndGetShape(call, ctx, data_sinfo, data_layout);
  Optional<ShapeExpr> weight_shape =
      CheckNdimPerLayoutAndGetShape(call, ctx, weight_sinfo, weight_layout);

  DataType out_dtype = attrs->out_dtype.is_void()
                           ? InferBinaryArithOpOutDtype(call, ctx, data_sinfo, weight_sinfo)
                           : attrs->out_dtype;
  if (!data_shape.defined() || !weight_shape.defined()) {
    return TensorStructInfo(out_dtype, out_layout.ndim());
  }

  Array<PrimExpr> data_NCHW_shape = data2NCHW.ForwardShape(data_shape.value()->values);
  Array<PrimExpr> weight_IOHW_shape = weight2IOHW.ForwardShape(weight_shape.value()->values);

  arith::Analyzer* analyzer = ctx->GetAnalyzer();
  PrimExpr input_channel_data = data_NCHW_shape[1];
  PrimExpr input_channel_kernel = weight_IOHW_shape[0];
  if (analyzer->CanProve(input_channel_data != input_channel_kernel)) {
    ctx->ReportFatal(
        Diagnostic::Error(call)
        << "Conv2dTranspose expects the channel size of the data should equal to the input channel "
           "size of the weight. However, the data channel size is "
        << input_channel_data << " while the weight input channel size is "
        << input_channel_kernel);
  } else if (!analyzer->CanProveEqual(input_channel_data, input_channel_kernel)) {
    // Todo(relax-team): Trust the input shape at this moment, and revisit
    // this condition with runtime shape check
  }
  if (analyzer->CanProve(floormod(input_channel_kernel, attrs->groups) != 0)) {
    ctx->ReportFatal(Diagnostic::Error(call)
                     << "Conv2dTranspose expects the number of input channels to be divisible by "
                        "the number of groups. However, the number of input channels is "
                     << input_channel_kernel << " while the number of groups is " << attrs->groups);
  } else if (!analyzer->CanProveEqual(floormod(input_channel_kernel, attrs->groups), 0)) {
    // Todo(relax-team): Trust the input shape at this moment, and revisit
    // this condition with runtime shape check
  }
  if (analyzer->CanProve(attrs->output_padding[0]->value >= attrs->strides[0]->value ||
                         attrs->output_padding[1]->value >= attrs->strides[1]->value)) {
    ctx->ReportFatal(Diagnostic::Error(call)
                     << "Conv2dTranspose expects the output padding less than the strides, but the "
                        "output padding is"
                     << attrs->output_padding << " while the strides are" << attrs->strides);
  } else if (!analyzer->CanProve(attrs->output_padding[0]->value < attrs->strides[0]->value &&
                                 attrs->output_padding[1]->value < attrs->strides[1]->value)) {
    // Todo(relax-team): Trust the input padding at this moment, and revisit
    // this condition with runtime shape check
  }

  PrimExpr input_h = data_NCHW_shape[2];
  PrimExpr input_w = data_NCHW_shape[3];
  PrimExpr kernel_h = weight_IOHW_shape[2];
  PrimExpr kernel_w = weight_IOHW_shape[3];
  PrimExpr padding_h = attrs->padding[0] + attrs->padding[2];
  PrimExpr padding_w = attrs->padding[1] + attrs->padding[3];

  std::vector<PrimExpr> out_NCHW_shape;
  out_NCHW_shape.resize(4);
  out_NCHW_shape[0] = data_NCHW_shape[0];
  out_NCHW_shape[1] = weight_IOHW_shape[1] * attrs->groups;

  PrimExpr out_h = (input_h - 1) * attrs->strides[0] - padding_h +
                   attrs->dilation[0] * (kernel_h - 1) + attrs->output_padding[0] + 1;
  PrimExpr out_w = (input_w - 1) * attrs->strides[1] - padding_w +
                   attrs->dilation[1] * (kernel_w - 1) + attrs->output_padding[1] + 1;
  out_NCHW_shape[2] = analyzer->Simplify(out_h);
  out_NCHW_shape[3] = analyzer->Simplify(out_w);

  Array<PrimExpr> out_shape = out2NCHW.BackwardShape(out_NCHW_shape);
  return TensorStructInfo(ShapeExpr(out_shape), out_dtype);
}

// TODO(relax-team): implement FInferMixedPrecision and FRelaxInferLayout for conv2d_transpose
// and unit test for mixed_precision
TVM_REGISTER_OP("relax.nn.conv2d_transpose")
    .set_num_inputs(2)
    .add_argument("data", "Tensor", "The input tensor.")
    .add_argument("weight", "Tensor", "The weight tensor.")
    .set_attrs_type<Conv2DTransposeAttrs>()
    .set_attr<FInferStructInfo>("FInferStructInfo", InferStructInfoConv2dTranspose);

}  // namespace relax
}  // namespace tvm

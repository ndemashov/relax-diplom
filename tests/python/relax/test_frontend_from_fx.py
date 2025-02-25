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
import pytest

import tvm
from tvm import relax
import tvm.testing
from tvm.script.parser import relax as R, tir as T


def verify_model(torch_model, input_info, binding, expected):
    from torch import fx
    from tvm.relax.frontend.torch import from_fx

    graph_model = fx.symbolic_trace(torch_model)
    mod = from_fx(graph_model, input_info)
    binding = {k: tvm.nd.array(v) for k, v in binding.items()}
    expected = relax.transform.BindParams("main", binding)(expected)
    tvm.ir.assert_structural_equal(mod, expected)


@tvm.testing.requires_gpu
def test_conv():
    import torch
    from torch.nn import Module

    torch.set_grad_enabled(False)
    torch.random.manual_seed(0)

    class Conv2D1(Module):
        def __init__(self):
            super().__init__()
            self.conv = torch.nn.Conv2d(3, 6, 7, bias=True)

        def forward(self, input):
            return self.conv(input)

    @tvm.script.ir_module
    class expected1:
        @R.function
        def main(
            input_1: R.Tensor((1, 3, 10, 10), dtype="float32"),
            w1: R.Tensor((6, 3, 7, 7), dtype="float32"),
            w2: R.Tensor((6,), dtype="float32"),
        ) -> R.Tensor((1, 6, 4, 4), dtype="float32"):
            # block 0
            with R.dataflow():
                lv1: R.Tensor((1, 6, 4, 4), dtype="float32") = R.nn.conv2d(
                    input_1,
                    w1,
                    strides=[1, 1],
                    padding=[0, 0, 0, 0],
                    dilation=[1, 1],
                    data_layout="NCHW",
                    kernel_layout="OIHW",
                    out_layout="NCHW",
                    out_dtype="float32",
                )
                lv2: R.Tensor((1, 6, 1, 1)) = R.reshape(w2, [1, 6, 1, 1])
                lv3: R.Tensor((1, 6, 4, 4), dtype="float32") = R.add(lv1, lv2)
                gv: R.Tensor((1, 6, 4, 4), dtype="float32") = lv3
                R.output(gv)
            return gv

    class Conv2D2(Module):
        def __init__(self):
            super().__init__()
            self.conv = torch.nn.Conv2d(3, 6, 7, bias=False)

        def forward(self, input):
            return self.conv(input)

    @tvm.script.ir_module
    class expected2:
        @R.function
        def main(
            input_1: R.Tensor((1, 3, 10, 10), dtype="float32"),
            w1: R.Tensor((6, 3, 7, 7), dtype="float32"),
        ) -> R.Tensor((1, 6, 4, 4), dtype="float32"):
            # block 0
            with R.dataflow():
                lv1: R.Tensor((1, 6, 4, 4), dtype="float32") = R.nn.conv2d(
                    input_1,
                    w1,
                    strides=[1, 1],
                    padding=[0, 0, 0, 0],
                    dilation=[1, 1],
                    data_layout="NCHW",
                    kernel_layout="OIHW",
                    out_layout="NCHW",
                    out_dtype="float32",
                )
                gv: R.Tensor((1, 6, 4, 4), dtype="float32") = lv1
                R.output(gv)
            return gv

    input_info = [([1, 3, 10, 10], "float32")]

    model = Conv2D1()
    binding = {"w1": model.conv.weight.numpy(), "w2": model.conv.bias.numpy()}
    verify_model(model, input_info, binding, expected1)

    model = Conv2D2()
    binding = {"w1": model.conv.weight.numpy()}
    verify_model(model, input_info, binding, expected2)


@tvm.testing.requires_gpu
def test_linear():
    import torch
    from torch.nn import Module

    torch.set_grad_enabled(False)
    torch.random.manual_seed(0)

    # nn.Linear
    class Dense1(Module):
        def __init__(self):
            super().__init__()
            self.linear = torch.nn.Linear(10, 7, bias=True)

        def forward(self, input):
            return self.linear(input)

    @tvm.script.ir_module
    class expected1:
        @R.function
        def main(
            input_1: R.Tensor((1, 3, 10, 10), dtype="float32"),
            w1: R.Tensor((7, 10), dtype="float32"),
            w2: R.Tensor((7,), dtype="float32"),
        ) -> R.Tensor((1, 3, 10, 7), dtype="float32"):
            # block 0
            with R.dataflow():
                lv: R.Tensor((10, 7), dtype="float32") = R.permute_dims(w1, axes=None)
                lv1: R.Tensor((1, 3, 10, 7), dtype="float32") = R.matmul(
                    input_1, lv, out_dtype="float32"
                )
                lv2: R.Tensor((1, 3, 10, 7), dtype="float32") = R.add(lv1, w2)
                gv: R.Tensor((1, 3, 10, 7), dtype="float32") = lv2
                R.output(gv)
            return gv

    class Dense2(Module):
        def __init__(self):
            super().__init__()
            self.linear = torch.nn.Linear(10, 7, bias=False)

        def forward(self, input):
            return self.linear(input)

    @tvm.script.ir_module
    class expected2:
        @R.function
        def main(
            input_1: R.Tensor((1, 3, 10, 10), dtype="float32"),
            w1: R.Tensor((7, 10), dtype="float32"),
        ) -> R.Tensor((1, 3, 10, 7), dtype="float32"):
            # block 0
            with R.dataflow():
                lv: R.Tensor((10, 7), dtype="float32") = R.permute_dims(w1, axes=None)
                lv1: R.Tensor((1, 3, 10, 7), dtype="float32") = R.matmul(
                    input_1, lv, out_dtype="float32"
                )
                gv: R.Tensor((1, 3, 10, 7), dtype="float32") = lv1
                R.output(gv)
            return gv

    input_info = [([1, 3, 10, 10], "float32")]

    model = Dense1()
    binding = {"w1": model.linear.weight.numpy(), "w2": model.linear.bias.numpy()}
    verify_model(model, input_info, binding, expected1)

    model = Dense2()
    binding = {"w1": model.linear.weight.numpy()}
    verify_model(model, input_info, binding, expected2)

    # matmul
    class MatMul1(Module):
        def __init__(self):
            super().__init__()

        def forward(self, x, y):
            return torch.matmul(x, y)

    @tvm.script.ir_module
    class expected3:
        @R.function
        def main(
            input_1: R.Tensor((10, 10), dtype="float32"),
            input_2: R.Tensor((10, 10), dtype="float32"),
        ) -> R.Tensor((10, 10), dtype="float32"):
            # block 0
            with R.dataflow():
                lv: R.Tensor((10, 10), dtype="float32") = R.matmul(
                    input_1, input_2, out_dtype="float32"
                )
                gv: R.Tensor((10, 10), dtype="float32") = lv
                R.output(gv)
            return gv

    verify_model(
        MatMul1(),
        [([10, 10], "float32"), ([10, 10], "float32")],
        {},
        expected3,
    )


@tvm.testing.requires_gpu
def test_bmm():
    import torch
    from torch.nn import Module

    torch.set_grad_enabled(False)
    torch.random.manual_seed(0)

    class BMM(Module):
        def __init__(self):
            super().__init__()

        def forward(self, x, y):
            return torch.bmm(x, y)

    @tvm.script.ir_module
    class Expected:
        @R.function
        def main(
            input_1: R.Tensor((4, 128, 256), dtype="float32"),
            input_2: R.Tensor((4, 256, 512), dtype="float32"),
        ) -> R.Tensor((4, 128, 512), dtype="float32"):
            # block 0
            with R.dataflow():
                lv: R.Tensor((4, 128, 512), dtype="float32") = R.matmul(
                    input_1, input_2, out_dtype="float32"
                )
                gv: R.Tensor((4, 128, 512), dtype="float32") = lv
                R.output(gv)
            return gv

    verify_model(
        BMM(),
        [((4, 128, 256), "float32"), ((4, 256, 512), "float32")],
        {},
        Expected,
    )


@tvm.testing.requires_gpu
def test_baddbmm():
    import torch
    from torch.nn import Module

    torch.set_grad_enabled(False)
    torch.random.manual_seed(0)

    class BAddBMM1(Module):
        def __init__(self):
            super().__init__()

        def forward(self, c, x, y):
            return torch.baddbmm(c, x, y)

    class BAddBMM2(Module):
        def __init__(self):
            super().__init__()

        def forward(self, c, x, y):
            return torch.baddbmm(c, x, y, alpha=2, beta=0)

    @tvm.script.ir_module
    class Expected1:
        @R.function
        def main(
            inp_0: R.Tensor((4, 128, 512), dtype="float32"),
            inp_1: R.Tensor((4, 128, 256), dtype="float32"),
            inp_2: R.Tensor((4, 256, 512), dtype="float32"),
        ) -> R.Tensor((4, 128, 512), dtype="float32"):
            with R.dataflow():
                lv: R.Tensor((4, 128, 512), dtype="float32") = R.matmul(inp_1, inp_2)
                lv1: R.Tensor((4, 128, 512), dtype="float32") = R.add(lv, inp_0)
                gv: R.Tensor((4, 128, 512), dtype="float32") = lv1
                R.output(gv)
            return gv

    @tvm.script.ir_module
    class Expected2:
        @R.function
        def main(
            inp_0: R.Tensor((4, 128, 512), dtype="float32"),
            inp_1: R.Tensor((4, 128, 256), dtype="float32"),
            inp_2: R.Tensor((4, 256, 512), dtype="float32"),
        ) -> R.Tensor((4, 128, 512), dtype="float32"):
            with R.dataflow():
                lv: R.Tensor((4, 128, 512), dtype="float32") = R.matmul(inp_1, inp_2)
                lv1: R.Tensor((4, 128, 512), dtype="float32") = R.multiply(
                    lv, R.const(2, "float32")
                )
                gv: R.Tensor((4, 128, 512), dtype="float32") = lv1
                R.output(gv)
            return gv

    verify_model(
        BAddBMM1(),
        [((4, 128, 512), "float32"), ((4, 128, 256), "float32"), ((4, 256, 512), "float32")],
        {},
        Expected1,
    )

    verify_model(
        BAddBMM2(),
        [((4, 128, 512), "float32"), ((4, 128, 256), "float32"), ((4, 256, 512), "float32")],
        {},
        Expected2,
    )


@tvm.testing.requires_gpu
def test_relu():
    import torch
    from torch.nn import Module

    torch.set_grad_enabled(False)

    class ReLU0(Module):
        def __init__(self):
            super().__init__()
            self.relu = torch.nn.ReLU()

        def forward(self, input):
            return self.relu(input)

    class ReLU1(Module):
        def forward(self, input):
            return torch.nn.functional.relu(input)

    @tvm.script.ir_module
    class expected:
        @R.function
        def main(
            input_1: R.Tensor((10, 10), dtype="float32")
        ) -> R.Tensor((10, 10), dtype="float32"):
            # block 0
            with R.dataflow():
                lv: R.Tensor((10, 10), dtype="float32") = R.nn.relu(input_1)
                gv: R.Tensor((10, 10), dtype="float32") = lv
                R.output(gv)
            return gv

    input_info = [([10, 10], "float32")]
    verify_model(ReLU0(), input_info, {}, expected)
    verify_model(ReLU1(), input_info, {}, expected)


@tvm.testing.requires_gpu
def test_relu6():
    import torch
    from torch.nn import Module

    torch.set_grad_enabled(False)

    class ReLU6(Module):
        def __init__(self):
            super().__init__()
            self.relu6 = torch.nn.ReLU6()

        def forward(self, input):
            return self.relu6(input)

    @tvm.script.ir_module
    class expected:
        @R.function
        def main(input: R.Tensor((10, 10), dtype="float32")) -> R.Tensor((10, 10), dtype="float32"):
            # block 0
            with R.dataflow():
                lv: R.Tensor((10, 10), dtype="float32") = R.clip(input, 0, 6)
                gv: R.Tensor((10, 10), dtype="float32") = lv
                R.output(gv)
            return gv

    input_info = [([10, 10], "float32")]
    verify_model(ReLU6(), input_info, {}, expected)


@tvm.testing.requires_gpu
def test_maxpool2d():
    import torch
    from torch.nn import Module

    torch.set_grad_enabled(False)
    torch.random.manual_seed(0)

    input_info = [([1, 3, 10, 10], "float32")]

    class MaxPool2d(Module):
        def __init__(self):
            super().__init__()
            self.pool = torch.nn.MaxPool2d(kernel_size=[1, 1])

        def forward(self, input):
            return self.pool(input)

    @tvm.script.ir_module
    class expected1:
        @R.function
        def main(
            input_1: R.Tensor((1, 3, 10, 10), dtype="float32")
        ) -> R.Tensor((1, 3, 10, 10), dtype="float32"):
            # block 0
            with R.dataflow():
                lv: R.Tensor((1, 3, 10, 10), dtype="float32") = R.nn.max_pool2d(
                    input_1,
                    pool_size=[1, 1],
                    strides=[1, 1],
                    dilation=[1, 1],
                    padding=[0, 0, 0, 0],
                    layout="NCHW",
                    out_layout="NCHW",
                )
                gv: R.Tensor((1, 3, 10, 10), dtype="float32") = lv
                R.output(gv)
            return gv

    class MaxPool2d2(Module):
        def __init__(self):
            super().__init__()
            self.pool = torch.nn.MaxPool2d(kernel_size=[2, 2], dilation=[2, 3])

        def forward(self, input):
            return self.pool(input)

    @tvm.script.ir_module
    class expected2:
        @R.function
        def main(
            input_1: R.Tensor((1, 3, 10, 10), dtype="float32")
        ) -> R.Tensor((1, 3, 4, 4), dtype="float32"):
            # block 0
            with R.dataflow():
                lv: R.Tensor((1, 3, 4, 4), dtype="float32") = R.nn.max_pool2d(
                    input_1,
                    pool_size=[2, 2],
                    strides=[2, 2],
                    dilation=[2, 3],
                    padding=[0, 0, 0, 0],
                    layout="NCHW",
                    out_layout="NCHW",
                )
                gv: R.Tensor((1, 3, 4, 4), dtype="float32") = lv
                R.output(gv)
            return gv

    class MaxPool2d3(Module):
        def __init__(self):
            super().__init__()
            self.pool = torch.nn.MaxPool2d(kernel_size=[4, 4], padding=2, stride=2)

        def forward(self, input):
            return self.pool(input)

    @tvm.script.ir_module
    class expected3:
        @R.function
        def main(
            input_1: R.Tensor((1, 3, 10, 10), dtype="float32")
        ) -> R.Tensor((1, 3, 6, 6), dtype="float32"):
            # block 0
            with R.dataflow():
                lv: R.Tensor((1, 3, 6, 6), dtype="float32") = R.nn.max_pool2d(
                    input_1,
                    pool_size=[4, 4],
                    strides=[2, 2],
                    dilation=[1, 1],
                    padding=[2, 2, 2, 2],
                    layout="NCHW",
                    out_layout="NCHW",
                )
                gv: R.Tensor((1, 3, 6, 6), dtype="float32") = lv
                R.output(gv)
            return gv

    verify_model(MaxPool2d(), input_info, {}, expected1)
    verify_model(MaxPool2d2(), input_info, {}, expected2)
    verify_model(MaxPool2d3(), input_info, {}, expected3)


@tvm.testing.requires_gpu
def test_avgpool2d():
    import torch
    from torch.nn import Module

    torch.set_grad_enabled(False)
    torch.random.manual_seed(0)

    input_info = [([1, 3, 10, 10], "float32")]

    class AvgPool2d(Module):
        def __init__(self):
            super().__init__()
            self.pool = torch.nn.AvgPool2d(kernel_size=[1, 1])

        def forward(self, input):
            return self.pool(input)

    @tvm.script.ir_module
    class expected1:
        @R.function
        def main(
            input_1: R.Tensor((1, 3, 10, 10), dtype="float32")
        ) -> R.Tensor((1, 3, 10, 10), dtype="float32"):
            # block 0
            with R.dataflow():
                lv: R.Tensor((1, 3, 10, 10), dtype="float32") = R.nn.avg_pool2d(
                    input_1,
                    pool_size=[1, 1],
                    strides=[1, 1],
                    dilation=[1, 1],
                    padding=[0, 0, 0, 0],
                    layout="NCHW",
                    out_layout="NCHW",
                )
                gv: R.Tensor((1, 3, 10, 10), dtype="float32") = lv
                R.output(gv)
            return gv

    class AvgPool2d2(Module):
        def __init__(self):
            super().__init__()
            self.pool = torch.nn.AvgPool2d(kernel_size=[4, 4], stride=2, padding=2, ceil_mode=True)

        def forward(self, input):
            return self.pool(input)

    class AvgPool2d3(Module):
        def forward(self, input):
            return torch.nn.functional.avg_pool2d(
                input, kernel_size=[4, 4], stride=2, padding=2, ceil_mode=True
            )

    @tvm.script.ir_module
    class expected2:
        @R.function
        def main(input_1: R.Tensor((1, 3, 10, 10), dtype="float32")):
            with R.dataflow():
                lv = R.nn.avg_pool2d(
                    input_1,
                    pool_size=[4, 4],
                    strides=[2, 2],
                    dilation=[1, 1],
                    padding=[2, 2, 2, 2],
                    ceil_mode=True,
                    layout="NCHW",
                    out_layout="NCHW",
                )
                gv = lv
                R.output(gv)
            return gv

    verify_model(AvgPool2d(), input_info, {}, expected1)
    verify_model(AvgPool2d2(), input_info, {}, expected2)
    verify_model(AvgPool2d3(), input_info, {}, expected2)


@tvm.testing.requires_gpu
def test_adaptive_avgpool2d():
    import torch
    from torch.nn import Module

    torch.set_grad_enabled(False)
    torch.random.manual_seed(0)

    input_info = [([1, 3, 10, 10], "float32")]

    class AdaptiveAvgPool2d0(Module):
        def __init__(self):
            super().__init__()
            self.pool = torch.nn.AdaptiveAvgPool2d([10, 10])

        def forward(self, input):
            return self.pool(input)

    class AdaptiveAvgPool2d1(Module):
        def forward(self, input):
            return torch.nn.functional.adaptive_avg_pool2d(input, [10, 10])

    @tvm.script.ir_module
    class expected1:
        @R.function
        def main(
            input_1: R.Tensor((1, 3, 10, 10), dtype="float32")
        ) -> R.Tensor((1, 3, 10, 10), dtype="float32"):
            # block 0
            with R.dataflow():
                lv: R.Tensor((1, 3, 10, 10), dtype="float32") = R.nn.adaptive_avg_pool2d(
                    input_1, output_size=[10, 10], layout="NCHW", out_layout="NCHW"
                )
                gv: R.Tensor((1, 3, 10, 10), dtype="float32") = lv
                R.output(gv)
            return gv

    verify_model(AdaptiveAvgPool2d0(), input_info, {}, expected1)
    verify_model(AdaptiveAvgPool2d1(), input_info, {}, expected1)


@tvm.testing.requires_gpu
def test_flatten():
    import torch
    from torch.nn import Module

    torch.set_grad_enabled(False)
    torch.random.manual_seed(0)

    input_info = [([1, 3, 10, 10], "float32")]

    class Flatten(Module):
        def __init__(self):
            super().__init__()
            self.f = torch.nn.Flatten(2, -1)

        def forward(self, input):
            return self.f(input)

    @tvm.script.ir_module
    class expected1:
        @R.function
        def main(
            input_1: R.Tensor((1, 3, 10, 10), dtype="float32")
        ) -> R.Tensor((1, 3, 100), dtype="float32"):
            # block 0
            with R.dataflow():
                lv: R.Tensor((1, 3, 100), dtype="float32") = R.reshape(input_1, (1, 3, 100))
                gv: R.Tensor((1, 3, 100), dtype="float32") = lv
                R.output(gv)
            return gv

    # call_module
    verify_model(Flatten(), input_info, {}, expected1)
    # call_method
    verify_model(torch.nn.Flatten(2, -1), input_info, {}, expected1)


@tvm.testing.requires_gpu
def test_batchnorm2d():
    import torch
    from torch.nn import Module

    torch.set_grad_enabled(False)
    torch.random.manual_seed(0)

    input_info = [([1, 3, 10, 10], "float32")]

    class BatchNorm2d(Module):
        def __init__(self):
            super().__init__()
            self.bn = torch.nn.BatchNorm2d(3)

        def forward(self, input):
            return self.bn(input)

    @tvm.script.ir_module
    class expected1:
        @R.function
        def main(
            input_1: R.Tensor((1, 3, 10, 10), dtype="float32"),
            w1: R.Tensor((3,), dtype="float32"),
            w2: R.Tensor((3,), dtype="float32"),
            w3: R.Tensor((3,), dtype="float32"),
            w4: R.Tensor((3,), dtype="float32"),
        ) -> R.Tensor((1, 3, 10, 10), dtype="float32"):
            # block 0
            with R.dataflow():
                lv: R.Tuple(
                    R.Tensor((1, 3, 10, 10), dtype="float32"),
                    R.Tensor((3,), dtype="float32"),
                    R.Tensor((3,), dtype="float32"),
                ) = R.nn.batch_norm(
                    input_1,
                    w1,
                    w2,
                    w3,
                    w4,
                    axis=1,
                    epsilon=1e-05,
                    center=True,
                    scale=True,
                )
                lv1: R.Tensor((1, 3, 10, 10), dtype="float32") = lv[0]
                gv: R.Tensor((1, 3, 10, 10), dtype="float32") = lv1
                R.output(gv)
            return gv

    model = BatchNorm2d()
    binding = {
        "w1": model.bn.weight.numpy(),
        "w2": model.bn.bias.numpy(),
        "w3": model.bn.running_mean.numpy(),
        "w4": model.bn.running_var.numpy(),
    }
    verify_model(BatchNorm2d(), input_info, binding, expected1)


@tvm.testing.requires_gpu
def test_embedding():
    import torch
    from torch.nn import Module

    torch.set_grad_enabled(False)
    torch.random.manual_seed(0)

    input_info = [([4], "int64")]

    class Embedding(Module):
        def __init__(self):
            super().__init__()
            self.embedding = torch.nn.Embedding(10, 3)

        def forward(self, input):
            return self.embedding(input)

    @tvm.script.ir_module
    class expected1:
        @R.function
        def main(
            input_1: R.Tensor((4,), dtype="int64"), w1: R.Tensor((10, 3), dtype="float32")
        ) -> R.Tensor((4, 3), dtype="float32"):
            # block 0
            with R.dataflow():
                lv: R.Tensor((4,), dtype="int32") = R.astype(input_1, dtype="int32")
                lv1: R.Tensor((4, 3), dtype="float32") = R.take(w1, lv, axis=0)
                gv: R.Tensor((4, 3), dtype="float32") = lv1
                R.output(gv)
            return gv

    model = Embedding()
    binding = {"w1": model.embedding.weight.numpy()}
    verify_model(model, input_info, binding, expected1)


@tvm.testing.requires_gpu
def test_dropout():
    import torch
    from torch.nn import Module

    torch.set_grad_enabled(False)
    torch.random.manual_seed(0)

    input_info = [([1, 3, 10, 10], "float32")]

    class Dropout1(Module):
        def __init__(self):
            super().__init__()
            self.dropout = torch.nn.Dropout(0.5)

        def forward(self, input):
            return self.dropout(input)

    class Dropout2(Module):
        def forward(self, input):
            return torch.dropout(input, 0.5, train=True)

    @tvm.script.ir_module
    class expected1:
        @R.function
        def main(
            input_1: R.Tensor((1, 3, 10, 10), dtype="float32")
        ) -> R.Tensor((1, 3, 10, 10), dtype="float32"):
            # block 0
            with R.dataflow():
                gv: R.Tensor((1, 3, 10, 10), dtype="float32") = input_1
                R.output(gv)
            return gv

    verify_model(Dropout1(), input_info, {}, expected1)
    verify_model(Dropout2(), input_info, {}, expected1)


@tvm.testing.requires_gpu
def test_layernorm():
    import torch
    from torch.nn import Module

    torch.set_grad_enabled(False)
    torch.random.manual_seed(0)

    input_info = [([1, 3, 10, 10], "float32")]

    class LayerNorm(Module):
        def __init__(self):
            super().__init__()
            self.ln = torch.nn.LayerNorm((10, 10))

        def forward(self, input):
            return self.ln(input)

    @tvm.script.ir_module
    class expected1:
        @R.function
        def main(
            input_1: R.Tensor((1, 3, 10, 10), dtype="float32"),
            w1: R.Tensor((10, 10), dtype="float32"),
            w2: R.Tensor((10, 10), dtype="float32"),
        ) -> R.Tensor((1, 3, 10, 10), dtype="float32"):
            # block 0
            with R.dataflow():
                lv: R.Tensor((1, 3, 10, 10), dtype="float32") = R.nn.layer_norm(
                    input_1,
                    w1,
                    w2,
                    axes=[-2, -1],
                    epsilon=1e-05,
                    center=True,
                    scale=True,
                )
                gv: R.Tensor((1, 3, 10, 10), dtype="float32") = lv
                R.output(gv)
            return gv

    model = LayerNorm()
    binding = {
        "w1": model.ln.weight.numpy(),
        "w2": model.ln.bias.numpy(),
    }
    verify_model(LayerNorm(), input_info, binding, expected1)


@tvm.testing.requires_gpu
def test_functional_layernorm():
    import torch
    from torch.nn import Module

    torch.set_grad_enabled(False)
    torch.random.manual_seed(0)

    input_info = [([1, 3, 10, 10], "float32")]

    class LayerNorm(Module):
        def __init__(self, shape):
            super().__init__()
            self.weight = torch.nn.Parameter(torch.ones(shape))
            self.bias = torch.nn.Parameter(torch.zeros(shape))

        def forward(self, input):
            return torch.nn.functional.layer_norm(
                input, self.weight.shape, self.weight, self.bias, 1e-5
            )

    @tvm.script.ir_module
    class expected1:
        @R.function
        def main(
            input_1: R.Tensor((1, 3, 10, 10), dtype="float32"),
            w1: R.Tensor((10, 10), dtype="float32"),
            w2: R.Tensor((10, 10), dtype="float32"),
        ) -> R.Tensor((1, 3, 10, 10), dtype="float32"):
            # block 0
            with R.dataflow():
                lv: R.Tensor((1, 3, 10, 10), dtype="float32") = R.nn.layer_norm(
                    input_1,
                    w1,
                    w2,
                    axes=[-2, -1],
                    epsilon=1e-05,
                    center=True,
                    scale=True,
                )
                gv: R.Tensor((1, 3, 10, 10), dtype="float32") = lv
                R.output(gv)
            return gv

    model = LayerNorm((10, 10))
    binding = {
        "w1": model.weight.numpy(),
        "w2": model.bias.numpy(),
    }
    verify_model(model, input_info, binding, expected1)


@tvm.testing.requires_gpu
def test_cross_entropy():
    import torch
    from torch.nn import Module

    torch.set_grad_enabled(False)
    torch.random.manual_seed(0)

    input_info = [([3, 2], "float32"), ([3], "int32")]

    class CrossEntropy1(Module):
        def __init__(self):
            super().__init__()
            self.loss = torch.nn.CrossEntropyLoss()

        def forward(self, logits, targets):
            return self.loss(logits, targets)

    @tvm.script.ir_module
    class expected1:
        @R.function
        def main(
            inp_0: R.Tensor((3, 2), dtype="float32"), inp_1: R.Tensor((3,), dtype="int32")
        ) -> R.Tensor((), dtype="float32"):
            with R.dataflow():
                lv: R.Tensor((3, 2), dtype="float32") = R.nn.log_softmax(inp_0, axis=-1)
                lv1: R.Tensor((), dtype="float32") = R.nn.nll_loss(
                    lv, inp_1, reduction="mean", ignore_index=-100
                )
                gv: R.Tensor((), dtype="float32") = lv1
                R.output(gv)
            return gv

    class CrossEntropy2(Module):
        def __init__(self):
            super().__init__()
            self.weight = torch.nn.Parameter(torch.ones((2,)))
            self.loss = torch.nn.CrossEntropyLoss(weight=self.weight)

        def forward(self, logits, targets):
            return self.loss(logits, targets)

    @tvm.script.ir_module
    class expected2:
        @R.function
        def main(
            inp_0: R.Tensor((3, 2), dtype="float32"),
            inp_1: R.Tensor((3,), dtype="int32"),
            w1: R.Tensor((2,), dtype="float32"),
        ) -> R.Tensor((), dtype="float32"):
            with R.dataflow():
                lv: R.Tensor((3, 2), dtype="float32") = R.nn.log_softmax(inp_0, axis=-1)
                lv1: R.Tensor((), dtype="float32") = R.nn.nll_loss(
                    lv,
                    inp_1,
                    w1,
                    reduction="mean",
                    ignore_index=-100,
                )
                gv: R.Tensor((), dtype="float32") = lv1
                R.output(gv)
            return gv

    class CrossEntropy3(Module):
        def __init__(self):
            super().__init__()
            self.loss = torch.nn.CrossEntropyLoss(ignore_index=1, reduction="sum")

        def forward(self, logits, targets):
            return self.loss(logits, targets)

    @tvm.script.ir_module
    class expected3:
        @R.function
        def main(
            inp_0: R.Tensor((3, 2), dtype="float32"), inp_1: R.Tensor((3,), dtype="int32")
        ) -> R.Tensor((), dtype="float32"):
            with R.dataflow():
                lv: R.Tensor((3, 2), dtype="float32") = R.nn.log_softmax(inp_0, axis=-1)
                lv1: R.Tensor((), dtype="float32") = R.nn.nll_loss(
                    lv, inp_1, reduction="sum", ignore_index=1
                )
                gv: R.Tensor((), dtype="float32") = lv1
                R.output(gv)
            return gv

    verify_model(CrossEntropy1(), input_info, {}, expected1)
    model = CrossEntropy2()
    binding = {"w1": model.loss.weight.numpy()}
    verify_model(model, input_info, binding, expected2)
    verify_model(CrossEntropy3(), input_info, {}, expected3)


@tvm.testing.requires_gpu
def test_functional_cross_entropy():
    import torch
    from torch.nn import Module

    torch.set_grad_enabled(False)
    torch.random.manual_seed(0)

    input_info = [([3, 10], "float32"), ([3], "int32")]

    class CrossEntropy(Module):
        def forward(self, logits, targets):
            return torch.nn.functional.cross_entropy(logits, targets)

    @tvm.script.ir_module
    class expected1:
        @R.function
        def main(
            inp_0: R.Tensor((3, 10), dtype="float32"), inp_1: R.Tensor((3,), dtype="int32")
        ) -> R.Tensor((), dtype="float32"):
            with R.dataflow():
                lv: R.Tensor((3, 10), dtype="float32") = R.nn.log_softmax(inp_0, axis=-1)
                lv1: R.Tensor((), dtype="float32") = R.nn.nll_loss(
                    lv, inp_1, reduction="mean", ignore_index=-100
                )
                gv: R.Tensor((), dtype="float32") = lv1
                R.output(gv)
            return gv

    model = CrossEntropy()
    verify_model(model, input_info, {}, expected1)


@tvm.testing.requires_gpu
def test_silu():
    import torch
    from torch.nn import Module

    torch.set_grad_enabled(False)
    torch.random.manual_seed(0)

    input_info = [([1, 3, 10, 10], "float32")]

    class SiLU(Module):
        def __init__(self):
            super().__init__()
            self.silu = torch.nn.SiLU()

        def forward(self, input):
            return self.silu(input)

    @tvm.script.ir_module
    class expected1:
        @R.function
        def main(
            input_1: R.Tensor((1, 3, 10, 10), dtype="float32")
        ) -> R.Tensor((1, 3, 10, 10), dtype="float32"):
            # block 0
            with R.dataflow():
                lv: R.Tensor((1, 3, 10, 10), dtype="float32") = R.nn.silu(input_1)
                gv: R.Tensor((1, 3, 10, 10), dtype="float32") = lv
                R.output(gv)
            return gv

    verify_model(SiLU(), input_info, {}, expected1)


@tvm.testing.requires_gpu
def test_groupnorm():
    import torch
    from torch.nn import Module

    torch.set_grad_enabled(False)
    torch.random.manual_seed(0)

    input_info = [([1, 3, 10, 10], "float32")]

    class GroupNorm(Module):
        def __init__(self):
            super().__init__()
            self.gn = torch.nn.GroupNorm(3, 3)

        def forward(self, input):
            return self.gn(input)

    @tvm.script.ir_module
    class expected1:
        @R.function
        def main(
            input_1: R.Tensor((1, 3, 10, 10), dtype="float32"),
            w1: R.Tensor((3,), dtype="float32"),
            w2: R.Tensor((3,), dtype="float32"),
        ) -> R.Tensor((1, 3, 10, 10), dtype="float32"):
            with R.dataflow():
                lv: R.Tensor((1, 3, 10, 10), dtype="float32") = R.nn.group_norm(
                    input_1,
                    w1,
                    w2,
                    num_groups=3,
                    channel_axis=1,
                    axes=[2, 3],
                    epsilon=1.0000000000000001e-05,
                    center=True,
                    scale=True,
                )
                gv: R.Tensor((1, 3, 10, 10), dtype="float32") = lv
                R.output(gv)
            return gv

    model = GroupNorm()
    binding = {
        "w1": model.gn.weight.numpy(),
        "w2": model.gn.bias.numpy(),
    }
    verify_model(model, input_info, binding, expected1)


@tvm.testing.requires_gpu
def test_softmax():
    import torch
    from torch.nn import Module

    torch.set_grad_enabled(False)
    torch.random.manual_seed(0)

    input_info = [([1, 3, 10, 10], "float32")]

    class Softmax(Module):
        def __init__(self):
            super().__init__()
            self.sm = torch.nn.Softmax(dim=1)

        def forward(self, input):
            return self.sm(input)

    @tvm.script.ir_module
    class expected1:
        @R.function
        def main(
            input_1: R.Tensor((1, 3, 10, 10), dtype="float32")
        ) -> R.Tensor((1, 3, 10, 10), dtype="float32"):
            # block 0
            with R.dataflow():
                lv: R.Tensor((1, 3, 10, 10), dtype="float32") = R.nn.softmax(input_1, axis=1)
                gv: R.Tensor((1, 3, 10, 10), dtype="float32") = lv
                R.output(gv)
            return gv

    verify_model(Softmax(), input_info, {}, expected1)


@tvm.testing.requires_gpu
def test_binary():
    import torch
    from torch.nn import Module

    torch.set_grad_enabled(False)
    torch.random.manual_seed(0)

    input_info1 = [([1, 3, 10, 10], "float32"), ([1, 3, 10, 10], "float32")]
    input_info2 = [([1, 3, 10, 10], "float32")]

    # Add
    class Add1(Module):
        def forward(self, lhs, rhs):
            return lhs + rhs

    @tvm.script.ir_module
    class expected1:
        @R.function
        def main(
            lhs: R.Tensor((1, 3, 10, 10), dtype="float32"),
            rhs: R.Tensor((1, 3, 10, 10), dtype="float32"),
        ) -> R.Tensor((1, 3, 10, 10), dtype="float32"):
            # block 0
            with R.dataflow():
                lv: R.Tensor((1, 3, 10, 10), dtype="float32") = R.add(lhs, rhs)
                gv: R.Tensor((1, 3, 10, 10), dtype="float32") = lv
                R.output(gv)
            return gv

    class Add2(Module):
        def forward(self, lhs):
            return lhs + 1.0

    @tvm.script.ir_module
    class expected2:
        @R.function
        def main(
            lhs_1: R.Tensor((1, 3, 10, 10), dtype="float32"),
        ) -> R.Tensor((1, 3, 10, 10), dtype="float32"):
            # block 0
            with R.dataflow():
                lv: R.Tensor((1, 3, 10, 10), dtype="float32") = R.add(lhs_1, R.const(1.0))
                gv: R.Tensor((1, 3, 10, 10), dtype="float32") = lv
                R.output(gv)
            return gv

    verify_model(Add1(), input_info1, {}, expected1)
    verify_model(Add2(), input_info2, {}, expected2)

    # Sub
    class Sub1(Module):
        def forward(self, lhs, rhs):
            return lhs - rhs

    @tvm.script.ir_module
    class expected3:
        @R.function
        def main(
            lhs_1: R.Tensor((1, 3, 10, 10), dtype="float32"),
            rhs_1: R.Tensor((1, 3, 10, 10), dtype="float32"),
        ) -> R.Tensor((1, 3, 10, 10), dtype="float32"):
            # block 0
            with R.dataflow():
                lv: R.Tensor((1, 3, 10, 10), dtype="float32") = R.subtract(lhs_1, rhs_1)
                gv: R.Tensor((1, 3, 10, 10), dtype="float32") = lv
                R.output(gv)
            return gv

    class Sub2(Module):
        def forward(self, lhs):
            return lhs - 1.0

    @tvm.script.ir_module
    class expected4:
        @R.function
        def main(
            lhs_1: R.Tensor((1, 3, 10, 10), dtype="float32"),
        ) -> R.Tensor((1, 3, 10, 10), dtype="float32"):
            # block 0
            with R.dataflow():
                lv: R.Tensor((1, 3, 10, 10), dtype="float32") = R.subtract(lhs_1, R.const(1.0))
                gv: R.Tensor((1, 3, 10, 10), dtype="float32") = lv
                R.output(gv)
            return gv

    verify_model(Sub1(), input_info1, {}, expected3)
    verify_model(Sub2(), input_info2, {}, expected4)

    # Mul
    class Mul1(Module):
        def forward(self, lhs, rhs):
            return lhs * rhs

    @tvm.script.ir_module
    class expected5:
        @R.function
        def main(
            lhs_1: R.Tensor((1, 3, 10, 10), dtype="float32"),
            rhs_1: R.Tensor((1, 3, 10, 10), dtype="float32"),
        ) -> R.Tensor((1, 3, 10, 10), dtype="float32"):
            # block 0
            with R.dataflow():
                lv: R.Tensor((1, 3, 10, 10), dtype="float32") = R.multiply(lhs_1, rhs_1)
                gv: R.Tensor((1, 3, 10, 10), dtype="float32") = lv
                R.output(gv)
            return gv

    class Mul2(Module):
        def forward(self, lhs):
            return lhs * 1.0

    @tvm.script.ir_module
    class expected6:
        @R.function
        def main(
            lhs_1: R.Tensor((1, 3, 10, 10), dtype="float32"),
        ) -> R.Tensor((1, 3, 10, 10), dtype="float32"):
            # block 0
            with R.dataflow():
                lv: R.Tensor((1, 3, 10, 10), dtype="float32") = R.multiply(lhs_1, R.const(1.0))
                gv: R.Tensor((1, 3, 10, 10), dtype="float32") = lv
                R.output(gv)
            return gv

    verify_model(Mul1(), input_info1, {}, expected5)
    verify_model(Mul2(), input_info2, {}, expected6)

    # True div
    class TrueDiv1(Module):
        def forward(self, lhs, rhs):
            return lhs / rhs

    @tvm.script.ir_module
    class expected7:
        @R.function
        def main(
            lhs_1: R.Tensor((1, 3, 10, 10), dtype="float32"),
            rhs_1: R.Tensor((1, 3, 10, 10), dtype="float32"),
        ) -> R.Tensor((1, 3, 10, 10), dtype="float32"):
            # block 0
            with R.dataflow():
                lv: R.Tensor((1, 3, 10, 10), dtype="float32") = R.divide(lhs_1, rhs_1)
                gv: R.Tensor((1, 3, 10, 10), dtype="float32") = lv
                R.output(gv)
            return gv

    class TrueDiv2(Module):
        def forward(self, lhs):
            return lhs / 1.0

    @tvm.script.ir_module
    class expected8:
        @R.function
        def main(
            lhs_1: R.Tensor((1, 3, 10, 10), dtype="float32"),
        ) -> R.Tensor((1, 3, 10, 10), dtype="float32"):
            # block 0
            with R.dataflow():
                lv: R.Tensor((1, 3, 10, 10), dtype="float32") = R.divide(lhs_1, R.const(1.0))
                gv: R.Tensor((1, 3, 10, 10), dtype="float32") = lv
                R.output(gv)
            return gv

    verify_model(TrueDiv1(), input_info1, {}, expected7)
    verify_model(TrueDiv2(), input_info2, {}, expected8)

    # Floor div
    class FloorDiv1(Module):
        def forward(self, lhs, rhs):
            return lhs // rhs

    @tvm.script.ir_module
    class expected9:
        @R.function
        def main(
            lhs_1: R.Tensor((1, 3, 10, 10), dtype="float32"),
            rhs_1: R.Tensor((1, 3, 10, 10), dtype="float32"),
        ) -> R.Tensor((1, 3, 10, 10), dtype="float32"):
            # block 0
            with R.dataflow():
                lv: R.Tensor((1, 3, 10, 10), dtype="float32") = R.floor_divide(lhs_1, rhs_1)
                gv: R.Tensor((1, 3, 10, 10), dtype="float32") = lv
                R.output(gv)
            return gv

    class FloorDiv2(Module):
        def forward(self, lhs):
            return lhs // 1.0

    @tvm.script.ir_module
    class expected10:
        @R.function
        def main(
            lhs_1: R.Tensor((1, 3, 10, 10), dtype="float32"),
        ) -> R.Tensor((1, 3, 10, 10), dtype="float32"):
            # block 0
            with R.dataflow():
                lv: R.Tensor((1, 3, 10, 10), dtype="float32") = R.floor_divide(lhs_1, R.const(1.0))
                gv: R.Tensor((1, 3, 10, 10), dtype="float32") = lv
                R.output(gv)
            return gv

    verify_model(FloorDiv1(), input_info1, {}, expected9)
    verify_model(FloorDiv2(), input_info2, {}, expected10)

    # Power
    class Power1(Module):
        def forward(self, lhs, rhs):
            return lhs**rhs

    @tvm.script.ir_module
    class expected11:
        @R.function
        def main(
            lhs_1: R.Tensor((1, 3, 10, 10), dtype="float32"),
            rhs_1: R.Tensor((1, 3, 10, 10), dtype="float32"),
        ) -> R.Tensor((1, 3, 10, 10), dtype="float32"):
            # block 0
            with R.dataflow():
                lv: R.Tensor((1, 3, 10, 10), dtype="float32") = R.power(lhs_1, rhs_1)
                gv: R.Tensor((1, 3, 10, 10), dtype="float32") = lv
                R.output(gv)
            return gv

    class Power2(Module):
        def forward(self, lhs):
            return lhs**1.0

    @tvm.script.ir_module
    class expected12:
        @R.function
        def main(
            lhs_1: R.Tensor((1, 3, 10, 10), dtype="float32"),
        ) -> R.Tensor((1, 3, 10, 10), dtype="float32"):
            # block 0
            with R.dataflow():
                lv: R.Tensor((1, 3, 10, 10), dtype="float32") = R.power(lhs_1, R.const(1.0))
                gv: R.Tensor((1, 3, 10, 10), dtype="float32") = lv
                R.output(gv)
            return gv

    verify_model(Power1(), input_info1, {}, expected11)
    verify_model(Power2(), input_info2, {}, expected12)

    # LT
    class LT1(Module):
        def forward(self, lhs, rhs):
            return lhs < rhs

    @tvm.script.ir_module
    class expected13:
        @R.function
        def main(
            lhs_1: R.Tensor((1, 3, 10, 10), dtype="float32"),
            rhs_1: R.Tensor((1, 3, 10, 10), dtype="float32"),
        ) -> R.Tensor((1, 3, 10, 10), dtype="bool"):
            # block 0
            with R.dataflow():
                lv: R.Tensor((1, 3, 10, 10), dtype="bool") = R.less(lhs_1, rhs_1)
                gv: R.Tensor((1, 3, 10, 10), dtype="bool") = lv
                R.output(gv)
            return gv

    class LT2(Module):
        def forward(self, lhs):
            return lhs < 1.0

    @tvm.script.ir_module
    class expected14:
        @R.function
        def main(
            lhs_1: R.Tensor((1, 3, 10, 10), dtype="float32"),
        ) -> R.Tensor((1, 3, 10, 10), dtype="bool"):
            # block 0
            with R.dataflow():
                lv: R.Tensor((1, 3, 10, 10), dtype="bool") = R.less(lhs_1, R.const(1.0))
                gv: R.Tensor((1, 3, 10, 10), dtype="bool") = lv
                R.output(gv)
            return gv

    verify_model(LT1(), input_info1, {}, expected13)
    verify_model(LT2(), input_info2, {}, expected14)


@tvm.testing.requires_gpu
def test_size():
    import torch
    from torch.nn import Module

    torch.set_grad_enabled(False)
    torch.random.manual_seed(0)

    input_info = [([1, 3, 10, 10], "float32")]

    class Size(Module):
        def forward(self, input):
            return input.size()

    @tvm.script.ir_module
    class expected1:
        @R.function
        def main(input_1: R.Tensor((1, 3, 10, 10), dtype="float32")) -> R.Shape([1, 3, 10, 10]):
            # block 0
            with R.dataflow():
                gv: R.Shape([1, 3, 10, 10]) = R.shape([1, 3, 10, 10])
                R.output(gv)
            return gv

    verify_model(Size(), input_info, {}, expected1)


@tvm.testing.requires_gpu
def test_squeeze():
    import torch
    from torch.nn import Module

    torch.set_grad_enabled(False)
    torch.random.manual_seed(0)

    input_info = [([3, 1, 4, 1], "float32")]

    class Squeeze1(Module):
        def forward(self, input):
            return input.squeeze(1)

    @tvm.script.ir_module
    class Expected1:
        @R.function
        def main(
            inp_0: R.Tensor((3, 1, 4, 1), dtype="float32")
        ) -> R.Tensor((3, 4, 1), dtype="float32"):
            with R.dataflow():
                lv: R.Tensor((3, 4, 1), dtype="float32") = R.squeeze(inp_0, axis=[1])
                gv: R.Tensor((3, 4, 1), dtype="float32") = lv
                R.output(gv)
            return gv

    class Squeeze2(Module):
        def forward(self, input):
            return input.squeeze()

    @tvm.script.ir_module
    class Expected2:
        @R.function
        def main(
            inp_0: R.Tensor((3, 1, 4, 1), dtype="float32")
        ) -> R.Tensor((3, 4), dtype="float32"):
            with R.dataflow():
                lv: R.Tensor((3, 4), dtype="float32") = R.squeeze(inp_0, axis=None)
                gv: R.Tensor((3, 4), dtype="float32") = lv
                R.output(gv)
            return gv

    verify_model(Squeeze1(), input_info, {}, Expected1)
    verify_model(Squeeze2(), input_info, {}, Expected2)


@tvm.testing.requires_gpu
def test_unsqueeze():
    import torch
    from torch.nn import Module

    torch.set_grad_enabled(False)
    torch.random.manual_seed(0)

    input_info = [([1, 3, 10, 10], "float32")]

    class Unsqueeze1(Module):
        def forward(self, input):
            return input.unsqueeze(1)

    @tvm.script.ir_module
    class expected1:
        @R.function
        def main(
            input_1: R.Tensor((1, 3, 10, 10), dtype="float32")
        ) -> R.Tensor((1, 1, 3, 10, 10), dtype="float32"):
            # block 0
            with R.dataflow():
                lv: R.Tensor((1, 1, 3, 10, 10), dtype="float32") = R.expand_dims(input_1, 1)
                gv: R.Tensor((1, 1, 3, 10, 10), dtype="float32") = lv
                R.output(gv)
            return gv

    class Unsqueeze2(Module):
        def forward(self, input):
            return input.unsqueeze(-1)

    @tvm.script.ir_module
    class expected2:
        @R.function
        def main(
            input_1: R.Tensor((1, 3, 10, 10), dtype="float32")
        ) -> R.Tensor((1, 3, 10, 10, 1), dtype="float32"):
            # block 0
            with R.dataflow():
                lv: R.Tensor((1, 3, 10, 10, 1), dtype="float32") = R.expand_dims(input_1, -1)
                gv: R.Tensor((1, 3, 10, 10, 1), dtype="float32") = lv
                R.output(gv)
            return gv

    verify_model(Unsqueeze1(), input_info, {}, expected1)
    verify_model(Unsqueeze2(), input_info, {}, expected2)


@tvm.testing.requires_gpu
def test_getattr():
    import torch
    from torch.nn import Module

    torch.set_grad_enabled(False)
    torch.random.manual_seed(0)

    input_info = [([1, 3, 10, 10], "float32")]

    class GetAttr1(Module):
        def forward(self, input):
            return input.shape

    @tvm.script.ir_module
    class expected1:
        @R.function
        def main(input_1: R.Tensor((1, 3, 10, 10), dtype="float32")) -> R.Shape([1, 3, 10, 10]):
            # block 0
            with R.dataflow():
                gv: R.Shape([1, 3, 10, 10]) = R.shape([1, 3, 10, 10])
                R.output(gv)
            return gv

    verify_model(GetAttr1(), input_info, {}, expected1)


@tvm.testing.requires_gpu
def test_getitem():
    import torch
    from torch.nn import Module

    torch.set_grad_enabled(False)
    torch.random.manual_seed(0)

    input_info = [([1, 3, 10, 10], "float32")]

    class Slice1(Module):
        def forward(self, x):
            return x[0, 1::2, :, :3]

    @tvm.script.ir_module
    class expected1:
        @R.function
        def main(
            x: R.Tensor((1, 3, 10, 10), dtype="float32")
        ) -> R.Tensor((1, 1, 10, 3), dtype="float32"):
            # block 0
            with R.dataflow():
                lv: R.Tensor((1, 1, 10, 3), dtype="float32") = R.strided_slice(
                    x,
                    axes=[0, 1, 2, 3],
                    begin=[0, 1, 0, 0],
                    end=[1, T.int64(3), T.int64(10), 3],
                    strides=[1, 2, 1, 1],
                )
                lv1: R.Tensor((1, 1, 10, 3), dtype="float32") = R.reshape(lv, (1, 1, 10, 3))
                gv: R.Tensor((1, 1, 10, 3), dtype="float32") = lv1
                R.output(gv)
            return gv

    verify_model(Slice1(), input_info, {}, expected1)


@tvm.testing.requires_gpu
def test_unary():
    import torch
    from torch.nn import Module

    torch.set_grad_enabled(False)
    torch.random.manual_seed(0)

    input_info = [([1, 3, 10, 10], "float32")]

    # sin
    class Sin(Module):
        def forward(self, input):
            return torch.sin(input)

    @tvm.script.ir_module
    class expected1:
        @R.function
        def main(
            input_1: R.Tensor((1, 3, 10, 10), dtype="float32")
        ) -> R.Tensor((1, 3, 10, 10), dtype="float32"):
            # block 0
            with R.dataflow():
                lv: R.Tensor((1, 3, 10, 10), dtype="float32") = R.sin(input_1)
                gv: R.Tensor((1, 3, 10, 10), dtype="float32") = lv
                R.output(gv)
            return gv

    verify_model(Sin(), input_info, {}, expected1)

    # cos
    class Cos(Module):
        def forward(self, input):
            return torch.cos(input)

    @tvm.script.ir_module
    class expected2:
        @R.function
        def main(
            input_1: R.Tensor((1, 3, 10, 10), dtype="float32")
        ) -> R.Tensor((1, 3, 10, 10), dtype="float32"):
            # block 0
            with R.dataflow():
                lv: R.Tensor((1, 3, 10, 10), dtype="float32") = R.cos(input_1)
                gv: R.Tensor((1, 3, 10, 10), dtype="float32") = lv
                R.output(gv)
            return gv

    verify_model(Cos(), input_info, {}, expected2)

    # sqrt
    class Sqrt(Module):
        def forward(self, input):
            return torch.sqrt(input)

    @tvm.script.ir_module
    class expected3:
        @R.function
        def main(
            input_1: R.Tensor((1, 3, 10, 10), dtype="float32")
        ) -> R.Tensor((1, 3, 10, 10), dtype="float32"):
            # block 0
            with R.dataflow():
                lv: R.Tensor((1, 3, 10, 10), dtype="float32") = R.sqrt(input_1)
                gv: R.Tensor((1, 3, 10, 10), dtype="float32") = lv
                R.output(gv)
            return gv

    verify_model(Sqrt(), input_info, {}, expected3)

    # sigmoid
    class Sigmoid(Module):
        def forward(self, input):
            return torch.sigmoid(input)

    @tvm.script.ir_module
    class expected4:
        @R.function
        def main(
            input_1: R.Tensor((1, 3, 10, 10), dtype="float32")
        ) -> R.Tensor((1, 3, 10, 10), dtype="float32"):
            # block 0
            with R.dataflow():
                lv: R.Tensor((1, 3, 10, 10), dtype="float32") = R.sigmoid(input_1)
                gv: R.Tensor((1, 3, 10, 10), dtype="float32") = lv
                R.output(gv)
            return gv

    verify_model(Sigmoid(), input_info, {}, expected4)

    # round
    class Round(Module):
        def forward(self, input):
            return torch.round(input)

    @tvm.script.ir_module
    class expected5:
        @R.function
        def main(
            input_1: R.Tensor((1, 3, 10, 10), dtype="float32")
        ) -> R.Tensor((1, 3, 10, 10), dtype="float32"):
            # block 0
            with R.dataflow():
                lv: R.Tensor((1, 3, 10, 10), dtype="float32") = R.round(input_1)
                gv: R.Tensor((1, 3, 10, 10), dtype="float32") = lv
                R.output(gv)
            return gv

    verify_model(Round(), input_info, {}, expected5)


@tvm.testing.requires_gpu
def test_gelu():
    import torch
    from torch.nn import Module

    torch.set_grad_enabled(False)
    torch.random.manual_seed(0)

    input_info = [([1, 3, 10, 10], "float32")]

    class Gelu(Module):
        def forward(self, input):
            return torch.nn.functional.gelu(input)

    @tvm.script.ir_module
    class expected1:
        @R.function
        def main(
            input_1: R.Tensor((1, 3, 10, 10), dtype="float32")
        ) -> R.Tensor((1, 3, 10, 10), dtype="float32"):
            # block 0
            with R.dataflow():
                lv: R.Tensor((1, 3, 10, 10), dtype="float32") = R.nn.gelu(input_1)
                gv: R.Tensor((1, 3, 10, 10), dtype="float32") = lv
                R.output(gv)
            return gv

    verify_model(Gelu(), input_info, {}, expected1)


@tvm.testing.requires_gpu
def test_tanh():
    import torch
    from torch.nn import Module

    torch.set_grad_enabled(False)
    torch.random.manual_seed(0)

    input_info = [([1, 3, 10, 10], "float32")]

    class Tanh(Module):
        def forward(self, input):
            return torch.tanh(input)

    @tvm.script.ir_module
    class expected1:
        @R.function
        def main(
            input_1: R.Tensor((1, 3, 10, 10), dtype="float32")
        ) -> R.Tensor((1, 3, 10, 10), dtype="float32"):
            # block 0
            with R.dataflow():
                lv: R.Tensor((1, 3, 10, 10), dtype="float32") = R.tanh(input_1)
                gv: R.Tensor((1, 3, 10, 10), dtype="float32") = lv
                R.output(gv)
            return gv

    verify_model(Tanh(), input_info, {}, expected1)


@tvm.testing.requires_gpu
def test_clamp():
    import torch
    from torch import fx
    from torch.nn import Module

    torch.set_grad_enabled(False)
    torch.random.manual_seed(0)

    input_info = [([1, 3, 10, 10], "float32")]

    class Clamp(Module):
        def forward(self, input):
            return torch.clamp(input, min=0.1, max=0.5)

    @tvm.script.ir_module
    class expected1:
        @R.function
        def main(
            input_1: R.Tensor((1, 3, 10, 10), dtype="float32")
        ) -> R.Tensor((1, 3, 10, 10), dtype="float32"):
            # block 0
            with R.dataflow():
                lv: R.Tensor((1, 3, 10, 10), dtype="float32") = R.clip(input_1, 0.1, 0.5)
                gv: R.Tensor((1, 3, 10, 10), dtype="float32") = lv
                R.output(gv)
            return gv

    verify_model(Clamp(), input_info, {}, expected1)

    from tvm.relax.frontend.torch import from_fx

    with pytest.raises(
        ValueError, match="TVM only supports constant max value for torch.clamp/clip"
    ):

        class Clamp_Error(Module):
            def forward(self, input):
                return torch.clamp(input, min=0.5, max=None)

        gm = fx.symbolic_trace(Clamp_Error())
        from_fx(gm, input_info)

    with pytest.raises(
        ValueError, match="TVM only supports constant min value for torch.clamp/clip"
    ):

        class Clamp_Error(Module):
            def forward(self, input):
                return torch.clamp(input, min=input, max=input)

        gm = fx.symbolic_trace(Clamp_Error())
        from_fx(gm, input_info)


@tvm.testing.requires_gpu
def test_interpolate():
    import torch
    from torch.nn import Module

    torch.set_grad_enabled(False)
    torch.random.manual_seed(0)

    input_info = [([1, 3, 10, 10], "float32")]

    class Interpolate(Module):
        def forward(self, input):
            return torch.nn.functional.interpolate(input, (5, 5))

    @tvm.script.ir_module
    class expected1:
        @R.function
        def main(
            input_1: R.Tensor((1, 3, 10, 10), dtype="float32")
        ) -> R.Tensor((1, 3, 5, 5), dtype="float32"):
            # block 0
            with R.dataflow():
                lv: R.Tensor((1, 3, 5, 5), dtype="float32") = R.image.resize2d(
                    input_1,
                    (5, 5),
                    roi=[0.000000, 0.000000, 0.000000, 0.000000],
                    layout="NCHW",
                    method="nearest_neighbor",
                    coordinate_transformation_mode="asymmetric",
                    rounding_method="round",
                    cubic_alpha=-0.5,
                    cubic_exclude=0,
                    extrapolation_value=0,
                    out_dtype="",
                )
                gv: R.Tensor((1, 3, 5, 5), dtype="float32") = lv
                R.output(gv)
            return gv

    verify_model(Interpolate(), input_info, {}, expected1)


@tvm.testing.requires_gpu
def test_addmm():
    import torch
    from torch.nn import Module

    torch.set_grad_enabled(False)
    torch.random.manual_seed(0)

    input_info = [
        ([10, 10], "float32"),
        ([10, 10], "float32"),
        ([10, 10], "float32"),
    ]

    class Addmm(Module):
        def forward(self, x1, x2, x3):
            return torch.addmm(x1, x2, x3)

    @tvm.script.ir_module
    class expected1:
        @R.function
        def main(
            x1: R.Tensor((10, 10), dtype="float32"),
            x2: R.Tensor((10, 10), dtype="float32"),
            x3: R.Tensor((10, 10), dtype="float32"),
        ) -> R.Tensor((10, 10), dtype="float32"):
            # block 0
            with R.dataflow():
                lv: R.Tensor((10, 10), dtype="float32") = R.matmul(x2, x3, out_dtype="float32")
                lv1: R.Tensor((10, 10), dtype="float32") = R.add(x1, lv)
                gv: R.Tensor((10, 10), dtype="float32") = lv1
                R.output(gv)
            return gv

    verify_model(Addmm(), input_info, {}, expected1)


@tvm.testing.requires_gpu
def test_split():
    import torch
    from torch.nn import Module

    torch.set_grad_enabled(False)
    torch.random.manual_seed(0)

    input_info = [([1, 3, 10, 10], "float32")]

    class Split(Module):
        def forward(self, input):
            return torch.split(input, 1, dim=1)

    @tvm.script.ir_module
    class expected1:
        @R.function
        def main(
            input_1: R.Tensor((1, 3, 10, 10), dtype="float32")
        ) -> R.Tuple(
            R.Tensor((1, 1, 10, 10), dtype="float32"),
            R.Tensor((1, 1, 10, 10), dtype="float32"),
            R.Tensor((1, 1, 10, 10), dtype="float32"),
        ):
            # block 0
            with R.dataflow():
                lv: R.Tuple(
                    R.Tensor((1, 1, 10, 10), dtype="float32"),
                    R.Tensor((1, 1, 10, 10), dtype="float32"),
                    R.Tensor((1, 1, 10, 10), dtype="float32"),
                ) = R.split(input_1, indices_or_sections=3, axis=1)
                gv: R.Tuple(
                    R.Tensor((1, 1, 10, 10), dtype="float32"),
                    R.Tensor((1, 1, 10, 10), dtype="float32"),
                    R.Tensor((1, 1, 10, 10), dtype="float32"),
                ) = lv
                R.output(gv)
            return gv

    verify_model(Split(), input_info, {}, expected1)


@tvm.testing.requires_gpu
def test_cumsum():
    import torch
    from torch.nn import Module

    torch.set_grad_enabled(False)
    torch.random.manual_seed(0)

    input_info = [([1, 2, 3, 4], "float32")]

    class Cumsum(Module):
        def forward(self, input):
            return torch.cumsum(input, dim=1, dtype=torch.int32)

    @tvm.script.ir_module
    class expected1:
        @R.function
        def main(
            input_1: R.Tensor((1, 2, 3, 4), dtype="float32")
        ) -> R.Tensor((1, 2, 3, 4), dtype="int32"):
            # block 0
            with R.dataflow():
                lv: R.Tensor((1, 2, 3, 4), dtype="int32") = R.cumsum(input_1, axis=1, dtype="int32")
                gv: R.Tensor((1, 2, 3, 4), dtype="int32") = lv
                R.output(gv)
            return gv

    verify_model(Cumsum(), input_info, {}, expected1)


@tvm.testing.requires_gpu
def test_chunk():
    import torch
    from torch.nn import Module

    torch.set_grad_enabled(False)
    torch.random.manual_seed(0)

    input_info = [([1, 3, 10, 10], "float32")]

    class Chunk(Module):
        def forward(self, input):
            return torch.chunk(input, 3, dim=1)

    @tvm.script.ir_module
    class Expected:
        @R.function
        def main(
            input_1: R.Tensor((1, 3, 10, 10), dtype="float32")
        ) -> R.Tuple(
            R.Tensor((1, 1, 10, 10), dtype="float32"),
            R.Tensor((1, 1, 10, 10), dtype="float32"),
            R.Tensor((1, 1, 10, 10), dtype="float32"),
        ):
            # block 0
            with R.dataflow():
                lv: R.Tuple(
                    R.Tensor((1, 1, 10, 10), dtype="float32"),
                    R.Tensor((1, 1, 10, 10), dtype="float32"),
                    R.Tensor((1, 1, 10, 10), dtype="float32"),
                ) = R.split(input_1, indices_or_sections=3, axis=1)
                gv: R.Tuple(
                    R.Tensor((1, 1, 10, 10), dtype="float32"),
                    R.Tensor((1, 1, 10, 10), dtype="float32"),
                    R.Tensor((1, 1, 10, 10), dtype="float32"),
                ) = lv
                R.output(gv)
            return gv

    verify_model(Chunk(), input_info, {}, Expected)


@tvm.testing.requires_gpu
def test_inplace_fill():
    import torch
    from torch.nn import Module

    torch.set_grad_enabled(False)
    torch.random.manual_seed(0)

    class InplaceFill(Module):
        def forward(self, input):
            input.fill_(1.5)
            return input

    @tvm.script.ir_module
    class Expected:
        @R.function
        def main(inp_0: R.Tensor((10, 10), dtype="float32")) -> R.Tensor((10, 10), dtype="float32"):
            with R.dataflow():
                lv: R.Tensor((10, 10), dtype="float32") = R.full(
                    R.shape([10, 10]), R.const(1.5, "float32"), dtype="float32"
                )
                gv: R.Tensor((10, 10), dtype="float32") = lv
                R.output(gv)
            return gv

    verify_model(InplaceFill(), [([10, 10], "float32")], {}, Expected)


@tvm.testing.requires_gpu
def test_arange():
    import numpy as np
    import torch
    from torch import fx
    from torch.nn import Module
    from tvm.relax.frontend.torch import from_fx

    torch.set_grad_enabled(False)
    torch.random.manual_seed(0)

    class Arange(Module):
        def forward(self, input):
            return torch.arange(0, 20, dtype=torch.int32)

    graph_model = fx.symbolic_trace(Arange())
    mod = from_fx(graph_model, [([10, 10], "float32")])
    assert len(mod["main"].body.blocks) == 1
    assert len(mod["main"].body.blocks[0].bindings) == 1
    assert isinstance(mod["main"].body.blocks[0].bindings[0].value, relax.Constant)
    tvm.testing.assert_allclose(
        mod["main"].body.blocks[0].bindings[0].value.data.numpy(), np.arange(0, 20, dtype="int32")
    )


@tvm.testing.requires_gpu
def test_empty():
    import torch
    from torch import fx
    from torch.nn import Module
    from tvm.relax.frontend.torch import from_fx

    torch.set_grad_enabled(False)
    torch.random.manual_seed(0)

    class Empty(Module):
        def forward(self, input):
            return torch.empty((10, 10), dtype=torch.float32)

    graph_model = fx.symbolic_trace(Empty())
    mod = from_fx(graph_model, [([10, 10], "float32")])
    assert len(mod["main"].body.blocks) == 1
    assert len(mod["main"].body.blocks[0].bindings) == 1
    assert isinstance(mod["main"].body.blocks[0].bindings[0].value, relax.Constant)
    assert mod["main"].body.blocks[0].bindings[0].value.data.shape == (10, 10)
    assert mod["main"].body.blocks[0].bindings[0].value.data.dtype == "float32"


@tvm.testing.requires_gpu
def test_tensor():
    import torch
    from torch import fx
    from torch.nn import Module
    from tvm.relax.frontend.torch import from_fx

    torch.set_grad_enabled(False)
    torch.random.manual_seed(0)

    class Empty1(Module):
        def forward(self, input):
            return torch.tensor(3, dtype=torch.float32)

    class Empty2(Module):
        def forward(self, input):
            return torch.tensor(3)

    graph_model1 = fx.symbolic_trace(Empty1())
    mod1 = from_fx(graph_model1, [([10, 10], "float32")])
    assert len(mod1["main"].body.blocks) == 1
    assert len(mod1["main"].body.blocks[0].bindings) == 1
    assert isinstance(mod1["main"].body.blocks[0].bindings[0].value, relax.Constant)
    assert mod1["main"].body.blocks[0].bindings[0].value.data.shape == ()
    assert mod1["main"].body.blocks[0].bindings[0].value.data.dtype == "float32"

    graph_model2 = fx.symbolic_trace(Empty2())
    mod2 = from_fx(graph_model2, [([10, 10], "float32")])
    assert len(mod2["main"].body.blocks) == 1
    assert len(mod2["main"].body.blocks[0].bindings) == 1
    assert isinstance(mod2["main"].body.blocks[0].bindings[0].value, relax.Constant)
    assert mod2["main"].body.blocks[0].bindings[0].value.data.shape == ()
    assert mod2["main"].body.blocks[0].bindings[0].value.data.dtype == "int64"


@tvm.testing.requires_gpu
def test_tril():
    import torch
    from torch.nn import Module

    torch.set_grad_enabled(False)
    torch.random.manual_seed(0)

    input_info = [([10, 10], "float32")]

    class Tril(Module):
        def forward(self, input):
            return torch.tril(input, 1)

    class InplaceTril(Module):
        def forward(self, input):
            input.tril_(1)
            return input

    @tvm.script.ir_module
    class expected1:
        @R.function
        def main(
            input_1: R.Tensor((10, 10), dtype="float32")
        ) -> R.Tensor((10, 10), dtype="float32"):
            # block 0
            with R.dataflow():
                lv: R.Tensor((10, 10), dtype="float32") = R.tril(input_1, 1)
                gv: R.Tensor((10, 10), dtype="float32") = lv
                R.output(gv)
            return gv

    verify_model(Tril(), input_info, {}, expected1)
    verify_model(InplaceTril(), input_info, {}, expected1)


@tvm.testing.requires_gpu
def test_triu():
    import torch
    from torch.nn import Module

    torch.set_grad_enabled(False)
    torch.random.manual_seed(0)

    input_info = [([10, 10], "float32")]

    class Triu(Module):
        def forward(self, input):
            return torch.triu(input, 1)

    class InplaceTriu(Module):
        def forward(self, input):
            input.triu_(1)
            return input

    @tvm.script.ir_module
    class expected1:
        @R.function
        def main(
            input_1: R.Tensor((10, 10), dtype="float32")
        ) -> R.Tensor((10, 10), dtype="float32"):
            # block 0
            with R.dataflow():
                lv: R.Tensor((10, 10), dtype="float32") = R.triu(input_1, 1)
                gv: R.Tensor((10, 10), dtype="float32") = lv
                R.output(gv)
            return gv

    verify_model(Triu(), input_info, {}, expected1)
    verify_model(InplaceTriu(), input_info, {}, expected1)


@tvm.testing.requires_gpu
def test_new_ones():
    import torch
    from torch.nn import Module

    torch.set_grad_enabled(False)
    torch.random.manual_seed(0)

    input_info = [([1, 2, 3], "float32")]

    class NewOnes(Module):
        def forward(self, x):
            return x.new_ones(1, 2, 3)

    @tvm.script.ir_module
    class expected1:
        @R.function
        def main(x: R.Tensor((1, 2, 3), dtype="float32")) -> R.Tensor((1, 2, 3), dtype="float32"):
            # block 0
            with R.dataflow():
                lv: R.Tensor((1, 2, 3), dtype="float32") = R.full(
                    (1, 2, 3), R.const(1, "float32"), dtype="float32"
                )
                gv: R.Tensor((1, 2, 3), dtype="float32") = lv
                R.output(gv)
            return gv

    verify_model(NewOnes(), input_info, {}, expected1)


@tvm.testing.requires_gpu
def test_expand():
    import torch
    from torch.nn import Module

    torch.set_grad_enabled(False)
    torch.random.manual_seed(0)

    input_info = [([1, 2, 3, 4], "float32")]

    class Expand(Module):
        def forward(self, x):
            return x.expand(4, 2, 3, 4)

    @tvm.script.ir_module
    class expected1:
        @R.function
        def main(
            x: R.Tensor((1, 2, 3, 4), dtype="float32")
        ) -> R.Tensor((4, 2, 3, 4), dtype="float32"):
            # block 0
            with R.dataflow():
                lv: R.Tensor((4, 2, 3, 4), dtype="float32") = R.broadcast_to(x, (4, 2, 3, 4))
                gv: R.Tensor((4, 2, 3, 4), dtype="float32") = lv
                R.output(gv)
            return gv

    verify_model(Expand(), input_info, {}, expected1)


@tvm.testing.requires_gpu
def test_reduce():
    import torch
    from torch.nn import Module

    torch.set_grad_enabled(False)
    torch.random.manual_seed(0)

    input_info = [([1, 2, 3, 4], "float32")]

    # sum
    class Sum(Module):
        def forward(self, x):
            return torch.sum(x, (2, 1))

    @tvm.script.ir_module
    class expected1:
        @R.function
        def main(
            inp_0: R.Tensor((1, 2, 3, 4), dtype="float32")
        ) -> R.Tensor((1, 4), dtype="float32"):
            # block 0
            with R.dataflow():
                lv: R.Tensor((1, 4), dtype="float32") = R.sum(inp_0, axis=[2, 1], keepdims=False)
                gv: R.Tensor((1, 4), dtype="float32") = lv
                R.output(gv)
            return gv

    verify_model(Sum(), input_info, {}, expected1)


@tvm.testing.requires_gpu
def test_datatype():
    import torch
    from torch.nn import Module

    torch.set_grad_enabled(False)
    torch.random.manual_seed(0)

    input_info = [([1, 2, 3, 4], "float32")]

    # float
    class ToFloat(Module):
        def forward(self, x):
            return x.float()

    @tvm.script.ir_module
    class expected1:
        @R.function
        def main(
            x: R.Tensor((1, 2, 3, 4), dtype="float32")
        ) -> R.Tensor((1, 2, 3, 4), dtype="float32"):
            # block 0
            with R.dataflow():
                lv: R.Tensor((1, 2, 3, 4), dtype="float32") = R.astype(x, dtype="float32")
                gv: R.Tensor((1, 2, 3, 4), dtype="float32") = lv
                R.output(gv)
            return gv

    verify_model(ToFloat(), input_info, {}, expected1)

    # half
    class ToHalf(Module):
        def forward(self, x):
            return x.half()

    @tvm.script.ir_module
    class expected2:
        @R.function
        def main(
            x: R.Tensor((1, 2, 3, 4), dtype="float32")
        ) -> R.Tensor((1, 2, 3, 4), dtype="float16"):
            # block 0
            with R.dataflow():
                lv: R.Tensor((1, 2, 3, 4), dtype="float16") = R.astype(x, dtype="float16")
                gv: R.Tensor((1, 2, 3, 4), dtype="float16") = lv
                R.output(gv)
            return gv

    verify_model(ToHalf(), input_info, {}, expected2)

    # type
    class Type(Module):
        def forward(self, x):
            return x.type(torch.float32)

    # type
    class TypeFromAttr(Module):
        def forward(self, x):
            return x.type(x.getattr("dtype"))

    # astype
    class AsType(Module):
        def forward(self, x):
            return x.astype(torch.float32)

    verify_model(Type(), input_info, {}, expected1)
    verify_model(TypeFromAttr(), input_info, {}, expected1)
    verify_model(AsType(), input_info, {}, expected1)


@tvm.testing.requires_gpu
def test_permute():
    import torch
    from torch.nn import Module

    torch.set_grad_enabled(False)
    torch.random.manual_seed(0)

    input_info = [([1, 2, 3, 4], "float32")]

    class Permute(Module):
        def forward(self, x):
            return x.permute(0, 3, 2, 1)

    @tvm.script.ir_module
    class expected1:
        @R.function
        def main(
            x: R.Tensor((1, 2, 3, 4), dtype="float32")
        ) -> R.Tensor((1, 4, 3, 2), dtype="float32"):
            # block 0
            with R.dataflow():
                lv: R.Tensor((1, 4, 3, 2), dtype="float32") = R.permute_dims(x, axes=[0, 3, 2, 1])
                gv: R.Tensor((1, 4, 3, 2), dtype="float32") = lv
                R.output(gv)
            return gv

    verify_model(Permute(), input_info, {}, expected1)


@tvm.testing.requires_gpu
def test_reshape():
    import torch
    from torch.nn import Module

    torch.set_grad_enabled(False)
    torch.random.manual_seed(0)

    input_info = [([1, 2, 3, 4], "float32")]

    class Reshape(Module):
        def forward(self, x):
            return x.reshape(2, 12)

    @tvm.script.ir_module
    class expected1:
        @R.function
        def main(x: R.Tensor((1, 2, 3, 4), dtype="float32")) -> R.Tensor((2, 12), dtype="float32"):
            # block 0
            with R.dataflow():
                lv: R.Tensor((2, 12), dtype="float32") = R.reshape(x, (2, 12))
                gv: R.Tensor((2, 12), dtype="float32") = lv
                R.output(gv)
            return gv

    verify_model(Reshape(), input_info, {}, expected1)


@tvm.testing.requires_gpu
def test_transpose():
    import torch
    from torch.nn import Module

    torch.set_grad_enabled(False)
    torch.random.manual_seed(0)

    input_info = [([1, 2, 3, 4], "float32")]

    class Transpose(Module):
        def forward(self, x):
            return x.transpose(1, 3)

    @tvm.script.ir_module
    class expected1:
        @R.function
        def main(
            x: R.Tensor((1, 2, 3, 4), dtype="float32")
        ) -> R.Tensor((1, 4, 3, 2), dtype="float32"):
            # block 0
            with R.dataflow():
                lv: R.Tensor((1, 4, 3, 2), dtype="float32") = R.permute_dims(x, axes=[0, 3, 2, 1])
                gv: R.Tensor((1, 4, 3, 2), dtype="float32") = lv
                R.output(gv)
            return gv

    verify_model(Transpose(), input_info, {}, expected1)


@tvm.testing.requires_gpu
def test_view():
    import torch
    from torch.nn import Module

    torch.set_grad_enabled(False)
    torch.random.manual_seed(0)

    input_info = [([1, 2, 3, 4], "float32")]

    class View(Module):
        def forward(self, x):
            return x.view(2, 12)

    @tvm.script.ir_module
    class expected1:
        @R.function
        def main(x: R.Tensor((1, 2, 3, 4), dtype="float32")) -> R.Tensor((2, 12), dtype="float32"):
            # block 0
            with R.dataflow():
                lv: R.Tensor((2, 12), dtype="float32") = R.reshape(x, (2, 12))
                gv: R.Tensor((2, 12), dtype="float32") = lv
                R.output(gv)
            return gv

    verify_model(View(), input_info, {}, expected1)


@tvm.testing.requires_gpu
def test_keep_params():
    import torch
    from torch import fx
    from torch.nn import Module
    from tvm.relax.frontend import detach_params
    from tvm.relax.frontend.torch import from_fx

    class Conv2D1(Module):
        def __init__(self):
            super().__init__()
            self.conv = torch.nn.Conv2d(3, 6, 7, bias=True)

        def forward(self, input):
            return self.conv(input)

    @tvm.script.ir_module
    class expected1:
        @R.function
        def main(
            input_1: R.Tensor((1, 3, 10, 10), dtype="float32"),
            w1: R.Tensor((6,), dtype="float32"),
            w2: R.Tensor((6, 3, 7, 7), dtype="float32"),
        ) -> R.Tensor((1, 6, 4, 4), dtype="float32"):
            R.func_attr({"num_input": 1})
            # block 0
            with R.dataflow():
                lv1: R.Tensor((1, 6, 4, 4), dtype="float32") = R.nn.conv2d(
                    input_1,
                    w2,
                    strides=[1, 1],
                    padding=[0, 0, 0, 0],
                    dilation=[1, 1],
                    data_layout="NCHW",
                    kernel_layout="OIHW",
                    out_layout="NCHW",
                    out_dtype="float32",
                )
                lv2: R.Tensor((1, 6, 1, 1), dtype="float32") = R.reshape(w1, [1, 6, 1, 1])
                lv3: R.Tensor((1, 6, 4, 4), dtype="float32") = R.add(lv1, lv2)
                gv: R.Tensor((1, 6, 4, 4), dtype="float32") = lv3
                R.output(gv)
            return gv

    model = Conv2D1()
    graph_model = fx.symbolic_trace(model)
    mod = from_fx(graph_model, [([1, 3, 10, 10], "float32")], keep_params_as_input=True)
    mod, params = detach_params(mod)
    tvm.ir.assert_structural_equal(mod, expected1)
    func = mod["main"]
    params = params["main"]

    assert len(params) == len(func.params) - 1
    for param_var, param_ndarray in zip(func.params[1:], params):
        assert tuple(x.value for x in param_var.struct_info.shape.values) == param_ndarray.shape
        assert param_var.struct_info.dtype == param_ndarray.dtype

    tvm.testing.assert_allclose(params[0].numpy(), model.conv.bias.detach().numpy())
    tvm.testing.assert_allclose(params[1].numpy(), model.conv.weight.detach().numpy())


@tvm.testing.requires_gpu
def test_unwrap_unit_return_tuple():
    import torch.fx as fx
    from torch.nn import Module
    from tvm.relax.frontend.torch import from_fx

    class Identity(Module):
        def __init__(self):
            super().__init__()

        def forward(self, x):
            return (x,)

    @tvm.script.ir_module
    class Expected:
        @R.function
        def main(
            inp_0: R.Tensor((256, 256), dtype="float32")
        ) -> R.Tensor((256, 256), dtype="float32"):
            with R.dataflow():
                gv: R.Tensor((256, 256), dtype="float32") = inp_0
                R.output(gv)
            return gv

    graph_model = fx.symbolic_trace(Identity())
    mod = from_fx(graph_model, [([256, 256], "float32")], unwrap_unit_return_tuple=True)
    tvm.ir.assert_structural_equal(mod, Expected)


@tvm.testing.requires_gpu
def test_argmax():
    import torch
    from torch.nn import Module

    class Argmax1(Module):
        def __init__(self) -> None:
            super().__init__()

        def forward(self, input):
            return torch.argmax(input, dim=-1)

    class Argmax2(Module):
        def __init__(self) -> None:
            super().__init__()

        def forward(self, input):
            return torch.argmax(input, dim=-1, keepdim=True)

    @tvm.script.ir_module
    class Expected1:
        @R.function
        def main(inp_0: R.Tensor((256, 256), dtype="float32")) -> R.Tensor((256,), dtype="int64"):
            with R.dataflow():
                lv: R.Tensor((256,), dtype="int64") = R.argmax(inp_0, axis=-1, keepdims=False)
                gv: R.Tensor((256,), dtype="int64") = lv
                R.output(gv)
            return gv

    @tvm.script.ir_module
    class Expected2:
        @R.function
        def main(inp_0: R.Tensor((256, 256), dtype="float32")) -> R.Tensor((256, 1), dtype="int64"):
            with R.dataflow():
                lv: R.Tensor((256, 1), dtype="int64") = R.argmax(inp_0, axis=-1, keepdims=True)
                gv: R.Tensor((256, 1), dtype="int64") = lv
                R.output(gv)
            return gv

    verify_model(Argmax1(), [([256, 256], "float32")], {}, Expected1)
    verify_model(Argmax2(), [([256, 256], "float32")], {}, Expected2)


@tvm.testing.requires_gpu
def test_argmin():
    import torch
    from torch.nn import Module

    class Argmin1(Module):
        def __init__(self) -> None:
            super().__init__()

        def forward(self, input):
            return torch.argmin(input)

    class Argmin2(Module):
        def __init__(self) -> None:
            super().__init__()

        def forward(self, input):
            return torch.argmin(input, keepdim=True)

    @tvm.script.ir_module
    class Expected1:
        @R.function
        def main(inp_0: R.Tensor((256, 256), dtype="float32")) -> R.Tensor((), dtype="int64"):
            with R.dataflow():
                lv: R.Tensor((), dtype="int64") = R.argmin(inp_0, axis=None, keepdims=False)
                gv: R.Tensor((), dtype="int64") = lv
                R.output(gv)
            return gv

    @tvm.script.ir_module
    class Expected2:
        @R.function
        def main(inp_0: R.Tensor((256, 256), dtype="float32")) -> R.Tensor((1, 1), dtype="int64"):
            with R.dataflow():
                lv: R.Tensor((1, 1), dtype="int64") = R.argmin(inp_0, axis=None, keepdims=True)
                gv: R.Tensor((1, 1), dtype="int64") = lv
                R.output(gv)
            return gv

    verify_model(Argmin1(), [([256, 256], "float32")], {}, Expected1)
    verify_model(Argmin2(), [([256, 256], "float32")], {}, Expected2)


if __name__ == "__main__":
    tvm.testing.main()

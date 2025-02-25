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
#include <tvm/relax/distributed/struct_info.h>

#include "./utils.h"

namespace tvm {
namespace script {
namespace printer {

class AttrPrinter : public tvm::AttrVisitor {
 public:
  explicit AttrPrinter(const ObjectPath& p, const IRDocsifier& d, Array<String>* keys,
                       Array<ExprDoc>* values)
      : p(p), d(d), keys(keys), values(values) {}

  void Visit(const char* key, double* value) final {
    keys->push_back(key);
    values->push_back(LiteralDoc::Float(*value, p->Attr(key)));
  }

  void Visit(const char* key, int64_t* value) final {
    keys->push_back(key);
    values->push_back(LiteralDoc::Int(*value, p->Attr(key)));
  }

  void Visit(const char* key, uint64_t* value) final {
    keys->push_back(key);
    values->push_back(LiteralDoc::Int(*value, p->Attr(key)));
  }

  void Visit(const char* key, int* value) final {
    keys->push_back(key);
    values->push_back(LiteralDoc::Int(*value, p->Attr(key)));
  }

  void Visit(const char* key, bool* value) final {
    keys->push_back(key);
    values->push_back(LiteralDoc::Boolean(*value, p->Attr(key)));
  }

  void Visit(const char* key, std::string* value) final {
    keys->push_back(key);
    values->push_back(LiteralDoc::Str(*value, p->Attr(key)));
  }

  void Visit(const char* key, DataType* value) final {
    keys->push_back(key);
    values->push_back(LiteralDoc::DataType(*value, p->Attr(key)));
  }

  void Visit(const char* key, runtime::ObjectRef* value) final {
    keys->push_back(key);
    values->push_back(d->AsDoc<ExprDoc>(*value, p->Attr(key)));
  }

  void Visit(const char* key, void** value) final {
    LOG(FATAL) << "TypeError: void is not allowed in Attrs";
  }

  void Visit(const char* key, runtime::NDArray* value) final {
    LOG(FATAL) << "TypeError: NDArray is not allowed in Attrs";
  }

  const ObjectPath& p;
  const IRDocsifier& d;
  Array<String>* keys;
  Array<ExprDoc>* values;
};

ExprDoc PrintCallee(const relax::Expr& n, const ObjectPath& n_p, const IRDocsifier& d) {
  // TODO(@junrushao): handle callee better
  if (const auto* ext = n.as<relax::ExternFuncNode>()) {
    return LiteralDoc::Str(ext->global_symbol, n_p);
  } else {
    return d->AsDoc<ExprDoc>(n, n_p);
  }
}

Optional<ExprDoc> PrintCallTIRDPSPacked(const relax::Call& n, const ObjectPath& n_p,
                                        const IRDocsifier& d) {
  static const Op& call_tir_op = Op::Get("relax.call_tir");
  static const Op& call_dps_packed_op = Op::Get("relax.call_dps_packed");
  if (!n->op.same_as(call_tir_op) && !n->op.same_as(call_dps_packed_op)) {
    return NullOpt;
  }
  ICHECK(n->args.size() == 2 || n->args.size() == 3);
  ICHECK(n->sinfo_args.size() == 1);
  Array<ExprDoc> args;
  Array<String> kwargs_keys;
  Array<ExprDoc> kwargs_values;
  // Step 1. Print n->args[0], the callee
  args.push_back(PrintCallee(n->args[0], n_p->Attr("args")->ArrayIndex(0), d));
  // Step 2. Print n->args[1], the input arguments
  args.push_back(d->AsDoc<ExprDoc>(n->args[1], n_p->Attr("args")->ArrayIndex(1)));
  // Step 3. Print n->sinfo_args, the output struct info
  relax::StructInfo o_sinfo = n->sinfo_args[0];
  ObjectPath o_sinfo_p = n_p->Attr("sinfo_args")->ArrayIndex(0);
  bool is_dtensor = false;
  kwargs_keys.push_back("out_sinfo");
  if (const auto* o = o_sinfo.as<relax::TupleStructInfoNode>()) {
    Array<ExprDoc> fields;
    ObjectPath fields_p = o_sinfo_p->Attr("fields");
    for (int i = 0, l = o->fields.size(); i < l; ++i) {
      if (o->fields[i].as<relax::distributed::DTensorStructInfoNode>()) {
        is_dtensor = true;
      }
      fields.push_back(d->AsDoc<ExprDoc>(o->fields[i], fields_p->ArrayIndex(i)));
    }
    kwargs_values.push_back(ListDoc(fields));
  } else {
    if (o_sinfo.as<relax::distributed::DTensorStructInfoNode>()) {
      is_dtensor = true;
    }
    kwargs_values.push_back(d->AsDoc<ExprDoc>(o_sinfo, o_sinfo_p));
  }
  if (n->op.same_as(call_dps_packed_op)) {
    return Relax(d, "call_dps_packed")->Call(args, kwargs_keys, kwargs_values);
  }
  // Step 4. Print n->args[2], the tir variables
  if (n->args.size() == 3) {
    kwargs_keys.push_back("tir_vars");
    kwargs_values.push_back(d->AsDoc<ExprDoc>(n->args[2], n_p->Attr("args")->ArrayIndex(2)));
  }
  if (is_dtensor) {
    return Relax(d, "dist.call_tir")->Call(args, kwargs_keys, kwargs_values);
  } else {
    return Relax(d, "call_tir")->Call(args, kwargs_keys, kwargs_values);
  }
}

TVM_STATIC_IR_FUNCTOR(IRDocsifier, vtable)
    .set_dispatch<relax::Call>(  //
        "", [](relax::Call n, ObjectPath n_p, IRDocsifier d) -> Doc {
          // Special case: call_tir, call_dps_packed
          if (Optional<ExprDoc> doc = PrintCallTIRDPSPacked(n, n_p, d)) {
            return doc.value();
          }
          ExprDoc prefix{nullptr};
          Array<ExprDoc> args;
          Array<String> kwargs_keys;
          Array<ExprDoc> kwargs_values;
          // Step 1. Print op
          if (const auto* op = n->op.as<relax::ExternFuncNode>()) {
            prefix = Relax(d, "call_packed");
            args.push_back(LiteralDoc::Str(op->global_symbol, n_p->Attr("op")));
          } else if (const auto* op = n->op.as<tvm::OpNode>()) {
            std::string name = op->name;
            if (name.rfind("relax.", 0) == 0) {
              prefix = Relax(d, name.substr(6));
            } else {
              prefix = IdDoc(name);
            }
            prefix->source_paths.push_back(n_p->Attr("op"));
          } else if (n->op->IsInstance<relax::VarNode>() ||
                     n->op->IsInstance<tvm::GlobalVarNode>()) {
            prefix = d->AsDoc<ExprDoc>(n->op, n_p->Attr("op"));
          } else {
            LOG(FATAL) << "TypeError: Unsupported op: " << n->op->GetTypeKey();
          }
          // Step 2. Print args
          if (!n->args.empty()) {
            args.push_back(PrintCallee(n->args[0], n_p->Attr("args")->ArrayIndex(0), d));
          }
          for (int i = 1, l = n->args.size(); i < l; ++i) {
            args.push_back(d->AsDoc<ExprDoc>(n->args[i], n_p->Attr("args")->ArrayIndex(i)));
          }
          // Step 3. Print attrs
          if (n->attrs.defined()) {
            if (n->op->IsInstance<relax::ExternFuncNode>()) {
              kwargs_keys.push_back("attrs_type_key");
              kwargs_values.push_back(LiteralDoc::Str(n->attrs->GetTypeKey(), n_p->Attr("attrs")));
            }
            if (const auto* attrs = n->attrs.as<tvm::DictAttrsNode>()) {
              std::vector<std::pair<String, ObjectRef>> sorted;
              for (const auto& kv : attrs->dict) {
                sorted.push_back(kv);
              }
              std::sort(sorted.begin(), sorted.end());
              for (const auto& kv : sorted) {
                kwargs_keys.push_back(kv.first);
                kwargs_values.push_back(
                    d->AsDoc<ExprDoc>(kv.second, n_p->Attr("attrs")->Attr(kv.first)));
              }
            } else {
              AttrPrinter printer(n_p->Attr("attrs"), d, &kwargs_keys, &kwargs_values);
              const_cast<BaseAttrsNode*>(n->attrs.get())->VisitAttrs(&printer);
            }
          }
          // Step 4. Print type_args
          if (n->sinfo_args.size() > 0) {
            ObjectPath sinfo_args_p = n_p->Attr("sinfo_args");
            Array<ExprDoc> sinfo_args;
            for (int i = 0, l = n->sinfo_args.size(); i < l; ++i) {
              sinfo_args.push_back(
                  d->AsDoc<ExprDoc>(n->sinfo_args[i], sinfo_args_p->ArrayIndex(i)));
            }
            kwargs_keys.push_back("sinfo_args");
            kwargs_values.push_back(TupleDoc(sinfo_args));
          }
          return prefix->Call(args, kwargs_keys, kwargs_values);
        });

TVM_SCRIPT_REPR(relax::CallNode, ReprPrintRelax);

}  // namespace printer
}  // namespace script
}  // namespace tvm

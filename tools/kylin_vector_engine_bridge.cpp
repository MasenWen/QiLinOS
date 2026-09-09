#include <cstdlib>
#include <iostream>
#include <memory>
#include <sstream>
#include <string>
#include <vector>

#include <nlohmann/json.hpp>

#include "kysdk-vector-engine-client/Database.h"

using json = nlohmann::json;
using namespace VectorDB;

namespace {

json fail(const std::string& message) {
    return json{{"ok", false}, {"error", message}};
}

json status_fail(const std::string& action, const Status& status) {
    std::ostringstream out;
    out << action << " failed code=" << static_cast<int>(status.Code())
        << " msg=" << status.Message();
    return fail(out.str());
}

std::string quote_string(const std::string& value) {
    std::string out = "\"";
    for (char ch : value) {
        if (ch == '\\' || ch == '"') {
            out += '\\';
        }
        out += ch;
    }
    out += '"';
    return out;
}

std::string metadata_expr(const std::string& key, const json& value) {
    if (value.is_string()) {
        return key + " == " + quote_string(value.get<std::string>());
    }
    return key + " == " + value.dump();
}

std::string build_expr(const json& filters) {
    if (!filters.is_object() || filters.empty()) {
        return "";
    }
    std::string expr;
    for (auto it = filters.begin(); it != filters.end(); ++it) {
        if (!expr.empty()) {
            expr += " && ";
        }
        expr += metadata_expr(it.key(), it.value());
    }
    return expr;
}

std::vector<float> to_vector(const json& value) {
    std::vector<float> result;
    for (const auto& item : value) {
        result.push_back(item.get<float>());
    }
    return result;
}

json ids_to_json(const IDArray& ids) {
    json out = json::array();
    for (auto id : ids.IntIDArray()) {
        out.push_back(id);
    }
    return out;
}

json query_rows(QueryResults& query_results) {
    json rows = json::array();
    FieldDataPtr id_field = query_results.GetFieldByName(DEFAULT_ID_FIELD_NAME);
    FieldDataPtr meta_field = query_results.GetFieldByName(DYNAMIC_FIELD_NAME);
    if (!id_field) {
        return rows;
    }
    auto id_ptr = std::static_pointer_cast<Int64FieldData>(id_field);
    std::shared_ptr<JsonFieldData> meta_ptr;
    if (meta_field) {
        meta_ptr = std::static_pointer_cast<JsonFieldData>(meta_field);
    }
    const auto& ids = id_ptr->Data();
    for (size_t i = 0; i < ids.size(); ++i) {
        json metadata = json::object();
        if (meta_ptr && i < meta_ptr->Data().size()) {
            metadata = meta_ptr->Data()[i];
        }
        rows.push_back({{"id", ids[i]}, {"metadata", metadata}});
    }
    return rows;
}

class Bridge {
public:
    json init(const json& request) {
        db_ = Database::Create();
        ConnectParam param(request.value("app_id", "nex_agent_memory"));
        param.SetConnectTimeout(request.value("connect_timeout_ms", 5000));
        auto status = db_->Connect(param);
        if (!status.IsOk()) {
            return status_fail("connect", status);
        }
        db_file_ = request.value("db_file", "");
        if (db_file_.empty()) {
            return fail("db_file is required");
        }
        status = db_->LoadDBFile(db_file_, false, "");
        if (!status.IsOk()) {
            return status_fail("load", status);
        }
        return json{{"ok", true}};
    }

    json handle(const json& request) {
        const std::string op = request.value("op", "");
        if (op == "init") return init(request);
        if (!db_) return fail("bridge is not initialized");
        if (op == "has_collection") return has_collection(request);
        if (op == "create_collection") return create_collection(request);
        if (op == "drop_collection") return drop_collection(request);
        if (op == "list_collections") return json{{"ok", true}, {"collections", json::array()}};
        if (op == "insert") return insert(request, false);
        if (op == "upsert") return upsert(request);
        if (op == "search") return search(request);
        if (op == "query") return query(request);
        if (op == "delete") return remove(request);
        if (op == "stats") return json{{"ok", true}, {"row_count", nullptr}};
        if (op == "close") return close();
        return fail("unknown op: " + op);
    }

private:
    json has_collection(const json& request) {
        bool exists = false;
        auto status = db_->HasCollection(request.value("collection", ""), exists);
        if (!status.IsOk()) return status_fail("has_collection", status);
        return json{{"ok", true}, {"exists", exists}};
    }

    json create_collection(const json& request) {
        const std::string collection = request.value("collection", "");
        const int dim = request.value("dim", 768);
        bool exists = false;
        auto status = db_->HasCollection(collection, exists);
        if (!status.IsOk()) return status_fail("has_collection", status);
        if (!exists) {
            status = db_->CreateCollection(collection, dim);
            if (!status.IsOk()) return status_fail("create_collection", status);
        }
        return json{{"ok", true}};
    }

    json drop_collection(const json& request) {
        const std::string collection = request.value("collection", "");
        bool exists = false;
        auto status = db_->HasCollection(collection, exists);
        if (!status.IsOk()) return status_fail("has_collection", status);
        if (exists) {
            status = db_->DropCollection(collection);
            if (!status.IsOk()) return status_fail("drop_collection", status);
        }
        return json{{"ok", true}};
    }

    json insert(const json& request, bool include_ids) {
        const std::string collection = request.value("collection", "");
        std::vector<std::vector<float>> vectors;
        std::vector<json> metas;
        std::vector<int64_t> ids;
        for (const auto& row : request.at("rows")) {
            vectors.push_back(to_vector(row.at("vector")));
            json metadata = row.value("metadata", json::object());
            if (row.contains("external_id")) {
                metadata["_external_id"] = row.at("external_id");
            }
            if (row.contains("text")) {
                metadata["text"] = row.at("text");
            }
            metas.push_back(metadata);
            if (include_ids) {
                ids.push_back(row.at("id").get<int64_t>());
            }
        }

        std::vector<FieldDataPtr> fields;
        if (include_ids) {
            fields.push_back(std::make_shared<Int64FieldData>(DEFAULT_ID_FIELD_NAME, ids));
        }
        fields.push_back(std::make_shared<FloatVecFieldData>(DEFAULT_VECTOR_FIELD_NAME, vectors));
        fields.push_back(std::make_shared<JsonFieldData>(DYNAMIC_FIELD_NAME, metas));

        DmlResults results;
        auto status = include_ids ? db_->Upsert(collection, fields, results)
                                  : db_->Insert(collection, fields, results);
        if (!status.IsOk()) return status_fail(include_ids ? "upsert" : "insert", status);
        return json{{"ok", true}, {"ids", ids_to_json(results.IdArray())}};
    }

    json upsert(const json& request) {
        json rows = request.value("rows", json::array());
        json prepared = request;
        prepared["rows"] = json::array();
        for (auto row : rows) {
            int64_t internal_id = row.value("id", int64_t{0});
            if (internal_id == 0 && row.contains("external_id")) {
                auto found = query_by_external_id(request.value("collection", ""), row.at("external_id").get<std::string>(), 1);
                if (!found.empty()) {
                    internal_id = found[0].value("id", int64_t{0});
                }
            }
            if (internal_id == 0) {
                json insert_req = request;
                insert_req["rows"] = json::array({row});
                return insert(insert_req, false);
            }
            row["id"] = internal_id;
            prepared["rows"].push_back(row);
        }
        return insert(prepared, true);
    }

    json search(const json& request) {
        SearchArguments args(request.value("collection", ""), request.value("top_k", 5));
        args.AddOutputField(DEFAULT_ID_FIELD_NAME);
        args.AddOutputField(DYNAMIC_FIELD_NAME);
        args.SetGuaranteeTimestamp(GuaranteeStrongTs());
        const std::string expr = build_expr(request.value("filters", json::object()));
        if (!expr.empty()) args.SetExpression(expr);
        std::vector<float> query_vec = to_vector(request.at("vector"));
        auto status = args.AddTargetVector(DEFAULT_VECTOR_FIELD_NAME, query_vec);
        if (!status.IsOk()) return status_fail("target_vector", status);

        SearchResults results;
        status = db_->Search(args, results, request.value("timeout_ms", 0));
        if (!status.IsOk()) return status_fail("search", status);

        json hits = json::array();
        for (auto& result : results.Results()) {
            auto& ids = result.Ids().IntIDArray();
            auto& scores = result.Scores();
            FieldDataPtr meta_field = result.OutputField(DYNAMIC_FIELD_NAME);
            std::shared_ptr<JsonFieldData> meta_ptr;
            if (meta_field) meta_ptr = std::static_pointer_cast<JsonFieldData>(meta_field);
            for (size_t i = 0; i < ids.size(); ++i) {
                json metadata = json::object();
                if (meta_ptr && i < meta_ptr->Data().size()) {
                    metadata = meta_ptr->Data()[i];
                }
                hits.push_back({
                    {"id", ids[i]},
                    {"external_id", metadata.value("_external_id", std::to_string(ids[i]))},
                    {"score", i < scores.size() ? scores[i] : 0.0f},
                    {"metadata", metadata},
                });
            }
        }
        return json{{"ok", true}, {"hits", hits}};
    }

    json query(const json& request) {
        QueryArguments args;
        args.SetCollectionName(request.value("collection", ""));
        args.AddOutputField(DEFAULT_ID_FIELD_NAME);
        args.AddOutputField(DYNAMIC_FIELD_NAME);
        std::string expr = request.value("expression", "");
        if (expr.empty()) {
            expr = build_expr(request.value("filters", json::object()));
        }
        if (!expr.empty()) args.SetExpression(expr);
        QueryResults results;
        auto status = db_->Query(args, results, request.value("timeout_ms", 0));
        if (!status.IsOk()) return status_fail("query", status);
        auto rows = query_rows(results);
        int limit = request.value("limit", 0);
        if (limit > 0 && rows.size() > static_cast<size_t>(limit)) {
            rows.erase(rows.begin() + limit, rows.end());
        }
        return json{{"ok", true}, {"rows", rows}};
    }

    json remove(const json& request) {
        const std::string collection = request.value("collection", "");
        std::string expression = request.value("expression", "");
        if (expression.empty() && request.contains("external_id")) {
            expression = metadata_expr("_external_id", request.at("external_id"));
        }
        if (expression.empty()) return fail("delete expression is required");
        DmlResults results;
        auto status = db_->Delete(collection, expression, results);
        if (!status.IsOk()) return status_fail("delete", status);
        return json{{"ok", true}, {"ids", ids_to_json(results.IdArray())}};
    }

    json close() {
        auto status = db_->Disconnect();
        if (!status.IsOk()) return status_fail("disconnect", status);
        db_.reset();
        return json{{"ok", true}};
    }

    json query_by_external_id(const std::string& collection, const std::string& external_id, int limit) {
        json req{
            {"op", "query"},
            {"collection", collection},
            {"filters", {{"_external_id", external_id}}},
            {"limit", limit},
        };
        auto res = query(req);
        if (!res.value("ok", false)) return json::array();
        return res.value("rows", json::array());
    }

    std::shared_ptr<Database> db_;
    std::string db_file_;
};

}  // namespace

int main() {
    Bridge bridge;
    std::string line;
    while (std::getline(std::cin, line)) {
        if (line.empty()) continue;
        auto* original_stdout = std::cout.rdbuf();
        try {
            json request = json::parse(line);
            std::ostringstream sdk_stdout;
            std::cout.rdbuf(sdk_stdout.rdbuf());
            json response = bridge.handle(request);
            std::cout.rdbuf(original_stdout);
            std::cout << response.dump() << std::endl;
            std::cout.flush();
            if (request.value("op", "") == "close") {
                break;
            }
        } catch (const std::exception& exc) {
            std::cout.rdbuf(original_stdout);
            std::cout << fail(exc.what()).dump() << std::endl;
            std::cout.flush();
        }
    }
    return 0;
}

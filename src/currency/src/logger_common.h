// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

#include "opentelemetry/exporters/otlp/otlp_grpc_exporter_factory.h"
#include "opentelemetry/logs/provider.h"
#include "opentelemetry/sdk/logs/logger.h"
#include "opentelemetry/sdk/logs/logger_provider_factory.h"
// BatchLogRecordProcessor: backed by a bounded queue that DROPS records when
// full instead of blocking the calling thread. SimpleLogRecordProcessor (its
// drop-in alternative) emits each record synchronously in-thread, which
// converts any OTLP-export slowdown (collector saturation, OpenSearch
// flood-stage block, etc.) into request-handler latency, which on this gRPC
// server has cascaded into thread-pool exhaustion and >2000s p50 Convert
// latency under load. Drop-on-full is the correct trade-off for a demo
// service whose primary signal is traces+metrics, not logs.
#include "opentelemetry/sdk/logs/batch_log_record_processor_factory.h"
#include "opentelemetry/sdk/logs/batch_log_record_processor_options.h"
#include "opentelemetry/sdk/logs/logger_context_factory.h"
#include "opentelemetry/exporters/otlp/otlp_grpc_log_record_exporter_factory.h"

using namespace std;
namespace nostd     = opentelemetry::nostd;
namespace otlp      = opentelemetry::exporter::otlp;
namespace logs      = opentelemetry::logs;
namespace logs_sdk  = opentelemetry::sdk::logs;

namespace
{
  void initLogger() {
    otlp::OtlpGrpcLogRecordExporterOptions loggerOptions;
    auto exporter  = otlp::OtlpGrpcLogRecordExporterFactory::Create(loggerOptions);
    logs_sdk::BatchLogRecordProcessorOptions processorOptions;
    auto processor = logs_sdk::BatchLogRecordProcessorFactory::Create(std::move(exporter), processorOptions);
    std::vector<std::unique_ptr<logs_sdk::LogRecordProcessor>> processors;
    processors.push_back(std::move(processor));
    auto context = logs_sdk::LoggerContextFactory::Create(std::move(processors));
    std::shared_ptr<logs::LoggerProvider> provider = logs_sdk::LoggerProviderFactory::Create(std::move(context));
    opentelemetry::logs::Provider::SetLoggerProvider(provider);
  }

  nostd::shared_ptr<opentelemetry::logs::Logger> getLogger(std::string name){
    auto provider = logs::Provider::GetLoggerProvider();
    return provider->GetLogger(name + "_logger", name, OPENTELEMETRY_SDK_VERSION);
  }
}

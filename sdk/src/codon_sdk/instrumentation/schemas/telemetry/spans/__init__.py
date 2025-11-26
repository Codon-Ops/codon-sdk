# Copyright 2025 Codon, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from enum import Enum


class CodonBaseSpanAttributes(Enum):
    OrgNamespace: str = "org.namespace"
    AgentFramework: str = "agent.framework.name"
    WorkloadId: str = "codon.workload.id"
    WorkloadLogicId: str = "codon.workload.logic_id"
    WorkloadRunId: str = "codon.workload.run_id"
    WorkloadName: str = "codon.workload.name"
    WorkloadVersion: str = "codon.workload.version"
    DeploymentId: str = "codon.workload.deployment_id"
    OrganizationId: str = "codon.organization.id"
    NodeLatencyMs: str = "codon.node.latency_ms"
    NodeInput: str = "codon.node.input"
    NodeOutput: str = "codon.node.output"
    NodeStatusCode: str = "codon.node.status_code"
    NodeErrorMessage: str = "codon.node.error_message"
    NodeRawAttributes: str = "codon.node.raw_attributes_json"
    TokenUsageJson: str = "codon.tokens.usage_json"
    TokenInput: str = "codon.tokens.input"
    TokenOutput: str = "codon.tokens.output"
    TokenTotal: str = "codon.tokens.total"
    ModelVendor: str = "codon.model.vendor"
    ModelIdentifier: str = "codon.model.id"
    NetworkCallsJson: str = "codon.network.calls_json"


class CodonSpanNames(Enum):
    AgentRun: str = "agent.run"
    AgentTool: str = "agent.tool"
    AgentWorkflow: str = "agent.workflow"
    AgentTask: str = "agent.task"
    AgentLLM: str = "agent.llm"
    AgentLLMCompletion: str = "agent.llm.completion"
    AgentLLMGeneration: str = "agent.llm.generation"
    AgentLLMUsage: str = "agent.llm.usage"
    AgentVectorDB: str = "agent.vector_db"
    AgentVectorDBQuery: str = "agent.vector_db.query"
    AgentVectorDBResult: str = "agent.vector_db.result"
    AgentVectorDBUpsert: str = "agent.vector_db.upsert"
    AgentVectorDBDelete: str = "agent.vector_db.delete"
    AgentVectorDBUpdate: str = "agent.vector_db.update"
    AgentVectorDBIndex: str = "agent.vector_db.index"
    AgentVectorDBCollection: str = "agent.vector_db.collection"
    AgentVectorDBDocument: str = "agent.vector_db.document"
    AgentVectorDBEmbedding: str = "agent.vector_db.embedding"
    AgentVectorDBMetadata: str = "agent.vector_db.metadata"
    AgentVectorDBFilter: str = "agent.vector_db.filter"
    AgentVectorDBScore: str = "agent.vector_db.score"
    AgentVectorDBDistance: str = "agent.vector_db.distance"
    AgentVectorDBAlgorithm: str = "agent.vector_db.algorithm"
    AgentVectorDBDimension: str = "agent.vector_db.dimension"
    AgentVectorDBMetric: str = "agent.vector_db.metric"
    AgentVectorDBShard: str = "agent.vector_db.shard"
    AgentVectorDBReplica: str = "agent.vector_db.replica"
    AgentVectorDBTerm: str = "agent.vector_db.term"
    AgentVectorDBField: str = "agent.vector_db.field"
    AgentVectorDBOperator: str = "agent.vector_db.operator"
    AgentVectorDBValue: str = "agent.vector_db.value"
    AgentVectorDBGroup: str = "agent.vector_db.group"
    AgentVectorDBAggregation: str = "agent.vector_db.aggregation"
    AgentVectorDBBucket: str = "agent.vector_db.bucket"
    AgentVectorDBRange: str = "agent.vector_db.range"
    AgentVectorDBDateRange: str = "agent.vector_db.date_range"
    AgentVectorDBHistogram: str = "agent.vector_db.histogram"
    AgentVectorDBDateHistogram: str = "agent.vector_db.date_histogram"
    AgentVectorDBTerms: str = "agent.vector_db.terms"
    AgentVectorDBSignificantTerms: str = "agent.vector_db.significant_terms"
    AgentVectorDBGeoDistance: str = "agent.vector_db.geo_distance"
    AgentVectorDBGeoBoundingBox: str = "agent.vector_db.geo_bounding_box"
    AgentVectorDBGeoPolygon: str = "agent.vector_db.geo_polygon"
    AgentVectorDBGeoShape: str = "agent.vector_db.geo_shape"
    AgentVectorDBPercolator: str = "agent.vector_db.percolator"
    AgentVectorDBMoreLikeThis: str = "agent.vector_db.more_like_this"
    AgentVectorDBScript: str = "agent.vector_db.script"
    AgentVectorDBScriptScore: str = "agent.vector_db.script_score"
    AgentVectorDBScriptFields: str = "agent.vector_db.script_fields"
    AgentVectorDBFunctionScore: str = "agent.vector_db.function_score"
    AgentVectorDBFieldValueFactor: str = "agent.vector_db.field_value_factor"
    AgentVectorDBDecayFunction: str = "agent.vector_db.decay_function"
    AgentVectorDBRandomScore: str = "agent.vector_db.random_score"
    AgentVectorDBWeight: str = "agent.vector_db.weight"
    AgentVectorDBLinear: str = "agent.vector_db.linear"
    AgentVectorDBExponential: str = "agent.vector_db.exponential"
    AgentVectorDBGauss: str = "agent.vector_db.gauss"
    AgentVectorDBSigmoid: str = "agent.vector_db.sigmoid"
    AgentVectorDBBoost: str = "agent.vector_db.boost"
    AgentVectorDBBoostMode: str = "agent.vector_db.boost_mode"
    AgentVectorDBMinScore: str = "agent.vector_db.min_score"
    AgentVectorDBMaxBoost: str = "agent.vector_db.max_boost"
    AgentVectorDBScoreMode: str = "agent.vector_db.score_mode"
    AgentVectorDBRescore: str = "agent.vector_db.rescore"
    AgentVectorDBRescoreQuery: str = "agent.vector_db.rescore_query"
    AgentVectorDBRescoreWindowSize: str = "agent.vector_db.rescore_window_size"
    AgentVectorDBRescoreQueryWeight: str = "agent.vector_db.rescore_query_weight"
    AgentVectorDBRescoreRescoreQueryWeight: str = (
        "agent.vector_db.rescore_rescore_query_weight"
    )
    AgentVectorDBRescoreScoreMode: str = "agent.vector_db.rescore_score_mode"
    AgentVectorDBCollapse: str = "agent.vector_db.collapse"
    AgentVectorDBCollapseField: str = "agent.vector_db.collapse_field"
    AgentVectorDBCollapseInnerHits: str = "agent.vector_db.collapse_inner_hits"
    AgentVectorDBCollapseMaxConcurrentGroupSearches: str = (
        "agent.vector_db.collapse_max_concurrent_group_searches"
    )
    AgentVectorDBContext: str = "agent.vector_db.context"
    AgentVectorDBSuggest: str = "agent.vector_db.suggest"
    AgentVectorDBSuggester: str = "agent.vector_db.suggester"
    AgentVectorDBSuggestText: str = "agent.vector_db.suggest_text"
    AgentVectorDBSuggestTerm: str = "agent.vector_db.suggest_term"
    AgentVectorDBSuggestPhrase: str = "agent.vector_db.suggest_phrase"
    AgentVectorDBSuggestCompletion: str = "agent.vector_db.suggest_completion"
    AgentVectorDBSuggestContext: str = "agent.vector_db.suggest_context"
    AgentVectorDBSuggestFuzzy: str = "agent.vector_db.suggest_fuzzy"
    AgentVectorDBSuggestRegex: str = "agent.vector_db.suggest_regex"
    AgentVectorDBSuggestPrefix: str = "agent.vector_db.suggest_prefix"
    AgentVectorDBSuggestMinLength: str = "agent.vector_db.suggest_min_length"
    AgentVectorDBSuggestShardSize: str = "agent.vector_db.suggest_shard_size"
    AgentVectorDBSuggestSize: str = "agent.vector_db.suggest_size"
    AgentVectorDBSuggestField: str = "agent.vector_db.suggest_field"
    AgentVectorDBSuggestAnalyzer: str = "agent.vector_db.suggest_analyzer"
    AgentVectorDBHighlight: str = "agent.vector_db.highlight"
    AgentVectorDBHighlightPreTags: str = "agent.vector_db.highlight_pre_tags"
    AgentVectorDBHighlightPostTags: str = "agent.vector_db.highlight_post_tags"
    AgentVectorDBHighlightFields: str = "agent.vector_db.highlight_fields"
    AgentVectorDBHighlightFragmentSize: str = (
        "agent.vector_db.highlight_fragment_size"
    )
    AgentVectorDBHighlightNumberOfFragments: str = (
        "agent.vector_db.highlight_number_of_fragments"
    )
    AgentVectorDBHighlightFragmenter: str = "agent.vector_db.highlight_fragmenter"
    AgentVectorDBHighlightOrder: str = "agent.vector_db.highlight_order"
    AgentVectorDBHighlightRequireFieldMatch: str = (
        "agent.vector_db.highlight_require_field_match"
    )
    AgentVectorDBHighlightBoundaryChars: str = (
        "agent.vector_db.highlight_boundary_chars"
    )
    AgentVectorDBHighlightBoundaryMaxScan: str = (
        "agent.vector_db.highlight_boundary_max_scan"
    )
    AgentVectorDBHighlightBoundaryScanner: str = (
        "agent.vector_db.highlight_boundary_scanner"
    )
    AgentVectorDBHighlightBoundaryScannerLocale: str = (
        "agent.vector_db.highlight_boundary_scanner_locale"
    )
    AgentVectorDBHighlightEncoder: str = "agent.vector_db.highlight_encoder"
    AgentVectorDBHighlightForceSource: str = "agent.vector_db.highlight_force_source"
    AgentVectorDBHighlightTagsSchema: str = "agent.vector_db.highlight_tags_schema"
    AgentVectorDBHighlightNoMatchSize: str = "agent.vector_db.highlight_no_match_size"
    AgentVectorDBHighlightPhraseLimit: str = "agent.vector_db.highlight_phrase_limit"
    AgentVectorDBHighlightMatchedFields: str = (
        "agent.vector_db.highlight_matched_fields"
    )
    AgentVectorDBSource: str = "agent.vector_db.source"
    AgentVectorDBSourceIncludes: str = "agent.vector_db.source_includes"
    AgentVectorDBSourceExcludes: str = "agent.vector_db.source_excludes"
    AgentVectorDBStoredFields: str = "agent.vector_db.stored_fields"
    AgentVectorDBDocvalueFields: str = "agent.vector_db.docvalue_fields"
    AgentVectorDBExplain: str = "agent.vector_db.explain"
    AgentVectorDBStats: str = "agent.vector_db.stats"
    AgentVectorDBTimeout: str = "agent.vector_db.timeout"

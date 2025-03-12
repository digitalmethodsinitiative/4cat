# Architecture for 'backend'

## Classes

:::mermaid
classDiagram
  class BasicHTTPScraper {
    category : str
    log_level : str
    prefix
    after_process()
    get_url()*
    not_found()
    parse(data)
    process(data)*
    work()
  }
  class BasicJSONScraper {
    parse(data)
  }
  class BasicProcessor {
    category : str
    config : NoneType
    dataset : NoneType
    db : NoneType
    description : str
    extension : str
    filepath : NoneType
    is_hidden : bool
    is_running_in_preset : bool
    job : NoneType
    owner : NoneType
    parameters
    source_dataset : NoneType
    source_file : NoneType
    abort()
    add_field_to_parent(field_name, new_data, which_parent, update_existing)
    after_process()
    create_standalone()
    exclude_followup_processors(processor_type)
    extract_archived_file_by_name(filename, archive_path, staging_area)
    get_extension(parent_dataset)
    get_mapped_item(item)
    get_options(parent_dataset, user)
    get_status()
    is_4cat_processor()
    is_filter()
    is_from_collector()
    is_rankable(multiple_items)
    is_top_dataset()
    iterate_archive_contents(path, staging_area, immediately_delete, filename_filter)
    map_item_method_available(dataset)
    process()*
    remove_files()
    unpack_archive_contents(path, staging_area)
    work()
    write_archive_and_finish(files, num_items, compression, finish)
    write_csv_items_and_finish(data)
  }
  class BasicWorker {
    INTERRUPT_CANCEL : int
    INTERRUPT_NONE : bool
    INTERRUPT_RETRY : int
    config : NoneType
    db : Database
    init_time : int
    interrupted : bool
    job : NoneType
    log : NoneType
    manager : NoneType
    max_workers : int
    modules : NoneType
    name : str
    queue : NoneType
    type : str
    abort()*
    clean_up()*
    is_4cat_class()
    is_4cat_processor()
    request_interrupt(level)
    run()
    work()*
  }
  class DatasetCanceller {
    max_workers : int
    type : str
    work()
  }
  class DatasourceMetrics {
    ensure_job : dict
    max_workers : int
    type : str
    data_stats()
    folder_size(path)
    general_stats()
    work()
  }
  class FourcatRestarterAndUpgrader {
    max_workers : int
    type : str
    work()
  }
  class InternalAPI {
    ensure_job : dict
    host : dict
    max_workers : int
    port : dict
    type : str
    api_response(client, address)
    process_request(request, payload)
    work()
  }
  class InternalAPIException {
  }
  class MySQLDatabase {
    connection : Connection
    cursor : NoneType
    log : NoneType
    close()
    commit()
    fetchall(query)
    fetchone(query)
    mogrify(query, replacements)
    query(query, replacements)
    rollback()
  }
  class ProcessorPreset {
    after_process()
    get_processor_pipeline()*
    process()
  }
  class QueryCanceller {
    max_workers : int
    type : str
    work()
  }
  class Search {
    import_error_count : int
    import_warning_count : int
    max_workers : int
    prefix : str
    return_cols : list
    type : str
    get_items(query)*
    import_from_file(path)
    items_to_archive(items, filepath)
    items_to_csv(results, filepath)
    items_to_ndjson(items, filepath)
    process()
    search(query)
  }
  class SearchWithScope {
    fetch_posts(post_ids, where, replacements)*
    fetch_threads(thread_ids)*
    get_items(query)*
    get_items_complex(query)*
    get_items_simple(query)*
    get_search_mode(query)
    get_thread_sizes(thread_ids, min_length)*
    search(query)
  }
  class TempFileCleaner {
    days_to_keep : int
    ensure_job : dict
    max_workers : int
    tracking_file
    type : str
    work()
  }
  class ThingExpirer {
    ensure_job : dict
    max_workers : int
    type : str
    expire_datasets()
    expire_notifications()
    expire_users()
    work()
  }
  class UpdateChecker {
    ensure_job : dict
    max_workers : int
    type : str
    work()
  }
  class WorkerManager {
    db : NoneType
    job_mapping : dict
    log : NoneType
    looping : bool
    modules : NoneType
    pool : list
    queue : NoneType
    worker_pool : dict
    abort(signal, stack)
    delegate()
    loop()
    request_interrupt(interrupt_level, job, remote_id, jobtype)
    validate_datasources()
  }
  ProcessorPreset --|> BasicProcessor
  BasicProcessor --|> BasicWorker
  BasicHTTPScraper --|> BasicWorker
  BasicJSONScraper --|> BasicHTTPScraper
  Search --|> BasicProcessor
  SearchWithScope --|> Search
  InternalAPI --|> BasicWorker
  DatasetCanceller --|> BasicWorker
  QueryCanceller --|> BasicWorker
  UpdateChecker --|> BasicWorker
  TempFileCleaner --|> BasicWorker
  DatasourceMetrics --|> BasicWorker
  ThingExpirer --|> BasicWorker
  FourcatRestarterAndUpgrader --|> BasicWorker
:::

## Packages

:::mermaid
classDiagram
  class backend {
  }
  class bootstrap {
  }
  class lib {
  }
  class database_mysql {
  }
  class manager {
  }
  class preset {
  }
  class processor {
  }
  class scraper {
  }
  class search {
  }
  class worker {
  }
  class workers {
  }
  class api {
  }
  class cancel_dataset {
  }
  class cancel_query {
  }
  class check_updates {
  }
  class cleanup_tempfiles {
  }
  class datasource_metrics {
  }
  class expire_items {
  }
  class restart_4cat {
  }
  bootstrap --> manager
  preset --> processor
  processor --> worker
  scraper --> worker
  search --> processor
  api --> worker
  cancel_dataset --> worker
  cancel_query --> worker
  check_updates --> worker
  cleanup_tempfiles --> worker
  datasource_metrics --> worker
  expire_items --> worker
  restart_4cat --> worker
:::

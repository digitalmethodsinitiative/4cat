# Architecture for 'common'

## Classes

:::mermaid
classDiagram
  class ConfigDummy {
  }
  class ConfigException {
  }
  class ConfigManager {
    cache : dict
    config_definition : dict
    core_settings : dict
    db : NoneType
    dbconn : NoneType
    tag_context : list
    delete_for_tag(attribute_name, tag)
    ensure_database()
    get(attribute_name, default, is_json, user, tags)
    get_active_tags(user, tags)
    get_all(is_json, user, tags)
    load_core_settings()
    load_user_settings()
    set(attribute_name, value, is_json, tag, overwrite_existing)
    with_db(db)
  }
  class ConfigWrapper {
    config
    request : NoneType
    tags : NoneType
    user : NoneType
    get()
    get_active_tags(user, tags)
    get_all()
    request_override(tags)
    set()
  }
  class CsvDialectException {
  }
  class DataSet {
    available_processors : NoneType
    children : NoneType
    data : NoneType
    db : NoneType
    folder : NoneType
    genealogy : NoneType
    is_new : bool
    key : str
    modules : NoneType
    no_status_updates : bool
    owners : NoneType
    parameters : NoneType
    preset_parent : NoneType
    result_file
    staging_areas : NoneType
    tagged_owners : NoneType
    add_owner(username, role)
    change_datasource(datasource)
    check_dataset_finished()
    clear_log()
    copy(shallow)
    copy_ownership_from(dataset, recursive)
    delete(commit, queue)
    delete_parameter(parameter, instant)
    detach()
    finish(num_rows)
    finish_with_error(error)
    get_all_children(recursive)
    get_annotation_fields()
    get_annotations()
    get_available_processors(user, exclude_hidden)
    get_breadcrumbs()
    get_columns()
    get_compatible_processors(user)
    get_extension()
    get_genealogy(inclusive)
    get_key(query, parameters, parent, time_offset)
    get_label(parameters, default)
    get_log_path()
    get_media_type()
    get_metadata()
    get_modules()
    get_own_processor()
    get_owners(role)
    get_owners_users(role)
    get_parameters()
    get_parent()
    get_place_in_queue(update)
    get_progress()
    get_result_url()
    get_results_folder_path()
    get_results_path()
    get_staging_area()
    get_status()
    get_version_url(file)
    is_accessible_by(username, role)
    is_dataset()
    is_expired(user)
    is_expiring(user)
    is_finished()
    is_from_collector()
    is_rankable(multiple_items)
    is_top_dataset()
    iterate_items(processor, warn_unmappable, map_missing)
    link_job(job)
    link_parent(key_parent)
    log(log)
    nearest(type_filter)
    refresh_owners()
    remove_owner(username)
    remove_staging_areas()
    reserve_result_file(parameters, extension)
    set_key(key)
    top_parent()
    update_children()
    update_label(label)
    update_progress(progress)
    update_status(status, is_final)
    update_version(version)
    warn_unmappable_item(item_count, processor, error_message, warn_admins)
  }
  class DataSetException {
  }
  class DataSetNotFoundException {
  }
  class Database {
    appname : str
    connection
    cursor : NoneType
    interruptable_job : NoneType
    interruptable_timeout : int
    interrupted : bool
    log : NoneType
    close()
    commit()
    delete(table, where, commit)
    execute(query, replacements)
    execute_many(query, commit, replacements)
    fetchall(query)
    fetchall_interruptable(queue, query)
    fetchone(query)
    get_cursor()
    insert(table, data, commit, safe, constraints, return_field)
    query(query, replacements, cursor)
    rollback()
    update(table, data, where, commit)
    upsert(table, data, commit, constraints)
  }
  class DatabaseQueryInterruptedException {
  }
  class DatasetItem {
    mapped_object
    missing_fields
    original
  }
  class DmiServiceManager {
    local_or_remote
    num_files_to_process : NoneType
    path_to_files : NoneType, Path
    path_to_results : NoneType, Path
    processed_files : int
    processor
    server_address
    server_file_collection_name : NoneType
    server_results_folder_name : NoneType
    check_gpu_memory_available(service_endpoint)
    check_progress()
    check_service_exists()
    count_local_files(directory)
    download_results(filenames_to_download, folder_name, local_output_dir, timeout)
    get_folder_name(dataset)
    process_files(input_file_dir, filenames, output_file_dir, server_file_collection_name, server_results_folder_name)
    process_results(local_output_dir)
    request_folder_files(folder_name)
    sanitize_filenames(filename)
    send_files(file_collection_name, results_name, files_to_upload, dir_with_files)
    send_request_and_wait_for_results(service_endpoint, data, wait_period, check_process, callback)
  }
  class DmiServiceManagerException {
  }
  class DsmConnectionError {
  }
  class DsmOutOfMemory {
  }
  class FourcatException {
    frame : NoneType
  }
  class FourcatModule {
  }
  class HTMLStripper {
    convert_charrefs : bool
    fed : list
    strict : bool
    get_data()
    handle_data(data)
  }
  class HashCache {
    hash_cache : dict
    hasher
    update_cache(value)
  }
  class Job {
    data : dict
    db : NoneType
    details
    is_claimed : bool
    is_finished : bool
    claim()
    finish(delete)
    get_by_ID(database)
    get_by_data(database)
    get_by_remote_ID(database, jobtype)
    get_place_in_queue()
    is_claimable()
    release(delay, claim_after)
  }
  class JobAlreadyExistsException {
  }
  class JobClaimedException {
  }
  class JobNotFoundException {
  }
  class JobQueue {
    db : NoneType
    log : NoneType
    add_job(jobtype, details, remote_id, claim_after, interval)
    get_all_jobs(jobtype, remote_id, restrict_claimable)
    get_job(jobtype, timestamp, restrict_claimable)
    get_job_count(jobtype)
    get_place_in_queue(job)
    release_all()
  }
  class Logger {
    alert_level : str
    db : NoneType
    levels : dict
    log_path : NoneType
    logger : NoneType
    previous_report : int
    print_logs : bool
    critical(message, frame)
    debug(message, frame)
    error(message, frame)
    fatal(message, frame)
    info(message, frame)
    log(message, level, frame)
    warning(message, frame)
  }
  class MapItemException {
  }
  class MappedItem {
    data
    message : str
    missing
    get_item_data(safe)
    get_message()
    get_missing_fields()
  }
  class MappedItemIncompleteException {
  }
  class MissingMappedField {
    value
  }
  class ModuleCollector {
    PROCESSOR : int
    WORKER : int
    datasources : dict
    ignore : list
    log_buffer : NoneType
    missing_modules : dict
    processors : dict
    workers : dict
    expand_datasources()
    is_4cat_class(object, only_processors)
    load_datasources()
    load_modules()
    load_worker_class(worker)
  }
  class NullAwareTextIOWrapper {
  }
  class ProcessorException {
  }
  class ProcessorInterruptedException {
  }
  class QueryException {
  }
  class QueryNeedsExplicitConfirmationException {
  }
  class QueryNeedsFurtherInputException {
    config
  }
  class QueryParametersException {
  }
  class QueueException {
  }
  class RequirementsNotMetException {
  }
  class SlackLogHandler {
    mapLogRecord(record)
  }
  class User {
    config : NoneType
    data : NoneType
    db : NoneType
    is_active : bool
    is_admin
    is_anonymous : bool
    is_authenticated : bool
    is_deactivated
    is_special
    name : str
    userdata : NoneType
    add_notification(notification, expires, allow_dismiss)
    add_tag(tag)
    authenticate()
    can_access_dataset(dataset, role)
    clear_token()
    delete(also_datasets)
    dismiss_notification(notification_id)
    email_token(new)
    generate_token(username, regenerate)
    get_by_login(db, name, password, config)
    get_by_name(db, name, config)
    get_by_token(db, token, config)
    get_id()
    get_name()
    get_notifications()
    get_token()
    get_value(key, default)
    remove_tag(tag)
    set_password(password)
    set_value(key, value)
    sort_user_tags()
    with_config(config)
  }
  class UserInput {
    OPTIONS_COSMETIC : tuple
    OPTION_CHOICE : str
    OPTION_DATASOURCES : str
    OPTION_DATE : str
    OPTION_DATERANGE : str
    OPTION_DIVIDER : str
    OPTION_FILE : str
    OPTION_HUE : str
    OPTION_INFO : str
    OPTION_MULTI : str
    OPTION_MULTI_SELECT : str
    OPTION_TEXT : str
    OPTION_TEXT_JSON : str
    OPTION_TEXT_LARGE : str
    OPTION_TOGGLE : str
    parse_all(options, input, silently_correct)
    parse_value(settings, choice, other_input, silently_correct)
  }
  class WebHookLogHandler {
    server_name : str
    emit(record)
  }
  class WorkerInterruptedException {
  }
  DataSet --|> FourcatModule
  DsmConnectionError --|> DmiServiceManagerException
  DsmOutOfMemory --|> DmiServiceManagerException
  ConfigException --|> FourcatException
  CsvDialectException --|> FourcatException
  DataSetException --|> FourcatException
  DataSetNotFoundException --|> DataSetException
  DatabaseQueryInterruptedException --|> WorkerInterruptedException
  JobAlreadyExistsException --|> QueueException
  JobClaimedException --|> QueueException
  JobNotFoundException --|> QueueException
  MapItemException --|> ProcessorException
  MappedItemIncompleteException --|> MapItemException
  ProcessorException --|> FourcatException
  ProcessorInterruptedException --|> WorkerInterruptedException
  QueryException --|> FourcatException
  QueryNeedsExplicitConfirmationException --|> QueryException
  QueryNeedsFurtherInputException --|> QueryException
  QueryParametersException --|> QueryException
  QueueException --|> FourcatException
  WorkerInterruptedException --|> FourcatException
  SlackLogHandler --|> WebHookLogHandler
  ConfigManager --* User : config
  Database --* ConfigManager : db
  ModuleCollector --* DataSet : modules
:::

## Packages

:::mermaid
classDiagram
  class common {
  }
  class config_manager {
  }
  class lib {
  }
  class config_definition {
  }
  class database {
  }
  class dataset {
  }
  class dmi_service_manager {
  }
  class exceptions {
  }
  class fourcat_module {
  }
  class helpers {
  }
  class item_mapping {
  }
  class job {
  }
  class logger {
  }
  class module_loader {
  }
  class queue {
  }
  class user {
  }
  class user_input {
  }
  config_manager --> config_definition
  config_manager --> database
  config_manager --> exceptions
  config_manager --> user_input
  config_definition --> user_input
  database --> exceptions
  dataset --> config_manager
  dataset --> exceptions
  dataset --> fourcat_module
  dataset --> helpers
  dataset --> item_mapping
  dataset --> job
  dataset --> module_loader
  dmi_service_manager --> helpers
  helpers --> config_manager
  helpers --> user_input
  job --> exceptions
  logger --> config_manager
  module_loader --> config_manager
  queue --> job
  user --> config_manager
  user --> dataset
  user --> exceptions
  user --> helpers
  user_input --> exceptions
  user_input --> helpers
:::

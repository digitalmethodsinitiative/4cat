# Architecture for 'webtool'

## Classes

:::mermaid
classDiagram
  class OpenAPICollector {
    apis : set
    endpoints : dict
    flask_app : NoneType
    type_map : dict
    endpoint(api_id)
    generate(api_id)
    schema_to_schema(schema)
  }
  class Pagination {
    has_next
    has_prev
    page
    pages
    per_page
    route : str
    route_args : dict
    total_count
    iter_pages(left_edge, left_current, right_current, right_edge)
  }
:::

## Packages

:::mermaid
classDiagram
  class webtool {
  }
  class lib {
  }
  class helpers {
  }
  class openapi_collector {
  }
  class template_filters {
  }
  class views {
  }
  class api_explorer {
  }
  class api_standalone {
  }
  class api_tool {
  }
  class views_admin {
  }
  class views_dataset {
  }
  class views_extensions {
  }
  class views_misc {
  }
  class views_restart {
  }
  class views_user {
  }
  webtool --> helpers
  webtool --> openapi_collector
  webtool --> views_admin
  template_filters --> webtool
  template_filters --> helpers
  api_explorer --> webtool
  api_explorer --> helpers
  api_standalone --> webtool
  api_standalone --> helpers
  api_tool --> webtool
  api_tool --> helpers
  views_admin --> webtool
  views_admin --> helpers
  views_dataset --> webtool
  views_dataset --> helpers
  views_dataset --> api_tool
  views_extensions --> webtool
  views_misc --> webtool
  views_misc --> helpers
  views_misc --> views_dataset
  views_restart --> webtool
  views_restart --> helpers
  views_user --> webtool
  views_user --> helpers
  views_user --> api_tool
:::

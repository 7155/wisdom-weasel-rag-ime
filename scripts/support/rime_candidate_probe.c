#include <stdio.h>
#include <stdlib.h>

#include "rime_api.h"

static int print_candidates(RimeApi *api, RimeSessionId session, const char *input) {
  api->clear_composition(session);
  if (!api->simulate_key_sequence(session, input)) {
    fprintf(stderr, "simulate_key_sequence failed for %s\n", input);
    return 2;
  }

  RIME_STRUCT(RimeContext, context);
  if (!api->get_context(session, &context)) {
    fprintf(stderr, "get_context failed for %s\n", input);
    return 3;
  }

  printf("%s", input);
  for (int index = 0; index < context.menu.num_candidates && index < 8; ++index) {
    const char *text = context.menu.candidates[index].text;
    printf("\t%s", text != NULL ? text : "");
  }
  printf("\n");
  api->free_context(&context);
  return 0;
}

int main(int argc, char **argv) {
  if (argc < 4) {
    fprintf(stderr, "usage: rime_candidate_probe SHARED_DATA USER_DATA INPUT...\n");
    return 64;
  }

  RimeApi *api = rime_get_api();
  if (api == NULL) {
    fprintf(stderr, "rime_get_api returned null\n");
    return 65;
  }

  RIME_STRUCT(RimeTraits, traits);
  traits.shared_data_dir = argv[1];
  traits.user_data_dir = argv[2];
  traits.distribution_name = "RAG-IME candidate probe";
  traits.distribution_code_name = "rag-ime-probe";
  traits.distribution_version = "1";
  traits.app_name = "rime.rag-ime-probe";
  traits.min_log_level = 3;
  traits.log_dir = "";

  api->setup(&traits);
  api->initialize(NULL);
  RimeSessionId session = api->create_session();
  if (session == 0 || !api->select_schema(session, "luna_pinyin_simp")) {
    fprintf(stderr, "cannot create luna_pinyin_simp session\n");
    api->finalize();
    return 66;
  }

  int result = 0;
  for (int index = 3; index < argc && result == 0; ++index) {
    result = print_candidates(api, session, argv[index]);
  }

  api->destroy_session(session);
  api->finalize();
  return result;
}

#include <coreai/vision/textrecognition.h>
#include <gio/gio.h>
#include <gio/giotypes.h>
#include <iostream>
#include <cstring>


void callback(TextRecognitionResult *result, void *user_data) {
    std::cout << text_recognition_result_get_value(result);
    if (user_data != nullptr) {
        GMainLoop *main_loop = static_cast<GMainLoop *>(user_data);
        g_main_loop_quit(main_loop);
    }
}

void test_ocr_from_file(const char* file_path) {

    TextRecognitionSession *session = text_recognition_create_session();

    TextRecognitionModelConfig *config = text_recognition_model_config_create();

    text_recognition_set_model_config(session, config);

    text_recognition_init_session(session);

    GMainLoop *main_loop = g_main_loop_new(nullptr, false);
    text_recognition_result_set_callback(session, callback, main_loop);
    text_recognition_recognize_text_from_image_file_async(session,
                                                          file_path);

    g_main_loop_run(main_loop);

    text_recognition_destroy_session(&session);
    text_recognition_model_config_destroy(&config);

    g_main_loop_unref(main_loop);
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        std::cout << "识别失败，未提供要识别的文件路径";
        return 1;
    }
    const char* file_path = argv[1];
    test_ocr_from_file(file_path);
    return 0;
}

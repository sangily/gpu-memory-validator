cmake_minimum_required(VERSION 3.18)
project(gpu_memory_validator LANGUAGES CXX)

include(CTest)
option(GMV_ENABLE_CUDA "Build the validator executable (requires CUDA)" OFF)

add_library(gmv_reference src/reference.cpp)
target_include_directories(gmv_reference PUBLIC include)
target_compile_features(gmv_reference PUBLIC cxx_std_17)

add_library(gmv_application src/cli.cpp src/report.cpp)
target_link_libraries(gmv_application PUBLIC gmv_reference)

if(BUILD_TESTING)
    add_executable(reference_tests tests/unit/test_reference.cpp)
    target_link_libraries(reference_tests PRIVATE gmv_reference)
    foreach(case_name IN ITEMS
        clean_patterns unordered_errors truncated_subset count_only
        single_element wrong_count wrong_actual wrong_expected duplicate_index
        out_of_range not_an_error missing_record excess_records count_only_with_record
        reset_between_calls spatial_golden_values spatial_wrong_fill spatial_swapped_words)
        add_test(NAME reference.${case_name} COMMAND reference_tests ${case_name})
    endforeach()
    add_executable(application_tests tests/unit/test_application.cpp)
    target_link_libraries(application_tests PRIVATE gmv_application)
    foreach(case_name IN ITEMS defaults inject unknown_option extra_arguments status_priority
            configuration invalid_numbers limits duplicate_options missing_values
            patterns_valid patterns_invalid patterns_limit load_config)
        add_test(NAME application.${case_name} COMMAND application_tests ${case_name})
    endforeach()
endif()

if(GMV_ENABLE_CUDA)
    # This project's measured GPU is an RTX 3060. Override for another device.
    if(NOT DEFINED CMAKE_CUDA_ARCHITECTURES)
        set(CMAKE_CUDA_ARCHITECTURES 86 CACHE STRING "CUDA target architectures")
    endif()
    enable_language(CUDA)
    find_package(CUDAToolkit REQUIRED)
    add_library(gmv_validator src/validator.cu)
    target_link_libraries(gmv_validator PUBLIC gmv_reference CUDA::cudart)
    set_target_properties(gmv_validator PROPERTIES
        CUDA_STANDARD 17 CUDA_STANDARD_REQUIRED YES)
    target_compile_options(gmv_validator PRIVATE
        $<$<COMPILE_LANGUAGE:CUDA>:-lineinfo>)
    add_executable(gpu_memory_validator src/main.cpp)
    target_link_libraries(gpu_memory_validator PRIVATE gmv_application gmv_validator)

    if(BUILD_TESTING)
        add_executable(runtime_tests tests/gpu/test_runtime.cpp)
        target_include_directories(runtime_tests PRIVATE src)
        target_link_libraries(runtime_tests PRIVATE gmv_application gmv_validator)
        foreach(case_name IN ITEMS
            success allocation_failure sync_failure prior_fail_then_error
            cleanup_failure primary_and_cleanup_failure recovery buffer_boundaries
            invalid_config repeat_failure batch_failure_cleanup batch_allocation_failure)
            add_test(NAME runtime.${case_name} COMMAND runtime_tests ${case_name})
            set_tests_properties(runtime.${case_name} PROPERTIES LABELS gpu TIMEOUT 30)
        endforeach()
    endif()
endif()

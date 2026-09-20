cmake_minimum_required(VERSION 3.18)
project(gpu_memory_validator LANGUAGES CXX)

include(CTest)
option(GMV_ENABLE_CUDA "Build the validator executable (requires CUDA)" OFF)

add_library(gmv_reference src/reference.cpp)
target_include_directories(gmv_reference PUBLIC include)
target_compile_features(gmv_reference PUBLIC cxx_std_17)

if(BUILD_TESTING)
    add_executable(reference_tests tests/unit/test_reference.cpp)
    target_link_libraries(reference_tests PRIVATE gmv_reference)
    foreach(case_name IN ITEMS
        clean_patterns unordered_errors truncated_subset count_only
        single_element wrong_count wrong_actual wrong_expected duplicate_index
        out_of_range not_an_error missing_record excess_records count_only_with_record
        reset_between_calls)
        add_test(NAME reference.${case_name} COMMAND reference_tests ${case_name})
    endforeach()
endif()

if(GMV_ENABLE_CUDA)
    # This project's measured GPU is an RTX 3060. Override for another device.
    if(NOT DEFINED CMAKE_CUDA_ARCHITECTURES)
        set(CMAKE_CUDA_ARCHITECTURES 86 CACHE STRING "CUDA target architectures")
    endif()
    enable_language(CUDA)
    add_executable(gpu_memory_validator src/validator.cu)
    target_link_libraries(gpu_memory_validator PRIVATE gmv_reference)
    set_target_properties(gpu_memory_validator PROPERTIES
        CUDA_STANDARD 17 CUDA_STANDARD_REQUIRED YES)
    target_compile_options(gpu_memory_validator PRIVATE
        $<$<COMPILE_LANGUAGE:CUDA>:-lineinfo>)
endif()

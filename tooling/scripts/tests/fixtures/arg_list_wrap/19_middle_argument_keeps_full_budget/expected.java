public class T
{
    void t()
    {
        result.add(
            arguments(
                TestOption.class,
                optionMap,
                List.of(
                    new DeprecatedOptionWarning(ENVIRONMENT,
                                                URL,
                                                URL.getEnvironmentVariable())),
                null));
    }
}

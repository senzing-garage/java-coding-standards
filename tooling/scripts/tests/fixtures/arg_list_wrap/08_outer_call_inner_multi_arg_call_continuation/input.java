public class Demo
{
    public Demo(Source source,
                Option option,
                String specifier,
                Set<Option> specifiedOptions)
    {
        super(source, option, specifier, buildErrorMessage(source,
                            option,
                            option.getDependencies(),
                            specifier,
                            specifiedOptions));
    }
}

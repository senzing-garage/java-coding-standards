public class Outer
{
    public static abstract class AbstractBuilder<
        E extends ConfigurableEnvironment,
        B extends AbstractBuilder<E, B>>
        extends BaseEnvironment.AbstractBuilder<E, B> implements Initializer
    {
    }
}

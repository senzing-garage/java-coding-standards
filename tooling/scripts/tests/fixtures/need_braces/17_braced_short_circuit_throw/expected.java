public class Foo
{
    public void method(Object input)
    {
        if (input == null) throw new IllegalArgumentException();
        process(input);
    }
}
